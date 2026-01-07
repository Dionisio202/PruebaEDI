from datetime import date
from dateutil.relativedelta import relativedelta

from rest_framework import serializers
from django.utils import timezone

from .models import (
    Patient,
    Instrument,
    InstrumentVersion,
    AgeBand,
    Question,
    Evaluation,
    Answer,
    EvaluationAreaResult,
    EvaluationDomainResult,
    EvaluationSummary,
)

from .services import EDIEvaluationService  # <-- Debe estar actualizado al nuevo esquema


# =========================================================
# Helpers de edad (ya no están en el modelo Patient)
# =========================================================
def _age_months(dob: date, reference_date: date) -> int:
    delta = relativedelta(reference_date, dob)
    return delta.years * 12 + delta.months


def _corrected_age_months(
    dob: date,
    reference_date: date,
    is_premature: bool,
    gestational_weeks: int | None,
) -> int:
    months = _age_months(dob, reference_date)
    # Solo corregir si es prematuro, tiene semanas, y menor de 24 meses (como tu lógica original)
    if is_premature and gestational_weeks and months < 24:
        correction_weeks = 40 - gestational_weeks
        correction_months = correction_weeks // 4
        return max(0, months - correction_months)
    return months


# =========================================================
# Serializers
# =========================================================
class AnswerInputSerializer(serializers.Serializer):
    """
    Acepta:
      - question_id (recomendado) o question_code (compatibilidad)
      - value (bool)
      - from_previous_group (opcional)
    Campos viejos se aceptan pero se ignoran (para no romper payloads viejos).
    """
    question_id = serializers.IntegerField(required=False)
    question_code = serializers.CharField(required=False, allow_blank=False)

    # Compatibilidad (payload viejo) - se ignoran
    answer_type = serializers.CharField(required=False, allow_null=True)
    area = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_critical = serializers.BooleanField(required=False)

    from_previous_group = serializers.BooleanField(default=False)
    value = serializers.BooleanField()

    def validate(self, attrs):
        qid = attrs.get("question_id")
        qcode = (attrs.get("question_code") or "").strip()

        if not qid and not qcode:
            raise serializers.ValidationError("Debe enviar question_id o question_code.")

        return attrs


class EvaluationCreateSerializer(serializers.Serializer):
    # -------------------------
    # Datos del paciente
    # -------------------------
    full_name = serializers.CharField(max_length=150)
    document_id = serializers.CharField(required=True)
    sex = serializers.ChoiceField(choices=Patient.Sex.choices, required=False, allow_null=True)
    date_of_birth = serializers.DateField(required=True)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    gestational_weeks = serializers.IntegerField(required=False, allow_null=True, min_value=20, max_value=42)
    is_premature = serializers.BooleanField(default=False)

    # -------------------------
    # Instrumento / versión
    # -------------------------
    instrument_code = serializers.CharField(required=False, default="EDI")
    instrument_version = serializers.CharField(required=False, allow_blank=True, default="")  # ej: "2024-02-12"

    # -------------------------
    # Evaluación
    # -------------------------
    evaluated_at = serializers.DateField(required=False)  # fecha de referencia para edad (si no, hoy)
    age_group = serializers.CharField(max_length=20)  # compat: lo tratamos como AgeBand.code
    use_corrected_age = serializers.BooleanField(default=True)

    answers = AnswerInputSerializer(many=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_document_id(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("El número de documento o historia clínica es obligatorio.")
        return value

    def validate_answers(self, value):
        if not value:
            raise serializers.ValidationError("Debe proporcionar al menos una respuesta.")
        return value

    def _resolve_instrument_version(self, instrument_code: str, version_str: str):
        instrument = Instrument.objects.filter(code=instrument_code).first()
        if not instrument:
            raise serializers.ValidationError({"instrument_code": f"No existe el instrumento '{instrument_code}'."})

        if version_str:
            iv = InstrumentVersion.objects.filter(instrument=instrument, version=version_str).first()
            if not iv:
                raise serializers.ValidationError({"instrument_version": f"No existe la versión '{version_str}' para '{instrument_code}'."})
            return iv

        iv = (
            InstrumentVersion.objects
            .filter(instrument=instrument, is_active=True)
            .order_by("-effective_from", "-id")
            .first()
        )
        if not iv:
            raise serializers.ValidationError({"instrument_version": f"No hay una versión activa para '{instrument_code}'."})
        return iv

    def create(self, validated_data):
        answers_data = validated_data.pop("answers")
        age_band_code = (validated_data.pop("age_group") or "").strip()  # compat
        use_corrected_age = validated_data.pop("use_corrected_age", True)
        notes = validated_data.pop("notes", "")

        instrument_code = (validated_data.pop("instrument_code") or "EDI").strip()
        version_str = (validated_data.pop("instrument_version") or "").strip()

        evaluated_at = validated_data.pop("evaluated_at", None) or timezone.localdate()

        # -------------------------
        # Crear o actualizar paciente
        # -------------------------
        patient_data = {
            "full_name": validated_data["full_name"],
            "document_id": validated_data.get("document_id"),
            "sex": validated_data.get("sex"),
            "date_of_birth": validated_data.get("date_of_birth"),
            "phone": validated_data.get("phone"),
            "gestational_weeks": validated_data.get("gestational_weeks"),
            "is_premature": validated_data.get("is_premature", False),
        }

        patient, _created = Patient.objects.update_or_create(
            document_id=patient_data["document_id"],
            defaults={k: v for k, v in patient_data.items() if v is not None}
        )

        # -------------------------
        # Resolver versión del instrumento
        # -------------------------
        iv = self._resolve_instrument_version(instrument_code, version_str)

        # -------------------------
        # Resolver AgeBand (antes age_group)
        # -------------------------
        age_band = AgeBand.objects.filter(instrument_version=iv, code=age_band_code).first()
        if not age_band:
            raise serializers.ValidationError({"age_group": f"No existe la banda/grupo '{age_band_code}' para {iv}."})

        # -------------------------
        # Calcular edad (corregida si aplica)
        # -------------------------
        dob = patient.date_of_birth
        raw_months = _age_months(dob, evaluated_at)

        corrected_months = _corrected_age_months(
            dob=dob,
            reference_date=evaluated_at,
            is_premature=patient.is_premature,
            gestational_weeks=patient.gestational_weeks,
        )

        used_corrected = bool(use_corrected_age and patient.is_premature and patient.gestational_weeks and raw_months < 24)
        age_in_months = corrected_months if used_corrected else raw_months

        # Validación elegante: edad debe caer dentro del rango del AgeBand elegido
        if not (age_band.min_months <= age_in_months <= age_band.max_months):
            raise serializers.ValidationError({
                "age_group": (
                    f"El grupo '{age_band.code}' no coincide con la edad calculada ({age_in_months} meses). "
                    f"Rango esperado: {age_band.min_months}-{age_band.max_months}."
                )
            })

        # -------------------------
        # Crear evaluación (cabecera)
        # -------------------------
        evaluation = Evaluation.objects.create(
            patient=patient,
            instrument_version=iv,
            evaluated_at=evaluated_at,
            used_corrected_age=used_corrected,
            age_in_months=age_in_months,
            age_band=age_band,
            notes=notes,
        )

        # -------------------------
        # Guardar respuestas (detalle)
        # -------------------------
        for a in answers_data:
            qid = a.get("question_id")
            qcode = (a.get("question_code") or "").strip()

            if qid:
                q = Question.objects.filter(instrument_version=iv, id=qid).first()
                if not q:
                    raise serializers.ValidationError({"answers": [f"question_id inválido: {qid} (no pertenece a {iv})."]})
            else:
                q = Question.objects.filter(instrument_version=iv, code=qcode).first()
                if not q:
                    raise serializers.ValidationError({"answers": [f"question_code inválido: '{qcode}' (no existe en {iv})."]})

            Answer.objects.create(
                evaluation=evaluation,
                question=q,
                from_previous_group=bool(a.get("from_previous_group", False)),
                value_bool=bool(a["value"]),
            )

        # -------------------------
        # Procesar evaluación (cálculos)
        # -------------------------
        # OJO: tu EDIEvaluationService debe estar adaptado al nuevo modelo:
        # - leer domain/area desde Answer.question
        # - escribir resultados en EvaluationAreaResult/EvaluationDomainResult/EvaluationSummary
        service = EDIEvaluationService(evaluation)
        service.calculate_evaluation()

        return evaluation


class EvaluationDetailSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    instrument_code = serializers.CharField(source="instrument_version.instrument.code", read_only=True)
    instrument_version = serializers.CharField(source="instrument_version.version", read_only=True)
    age_band = serializers.CharField(source="age_band.code", read_only=True)

    diagnosis = serializers.SerializerMethodField()
    final_status = serializers.SerializerMethodField()
    trace = serializers.SerializerMethodField()

    answers = serializers.SerializerMethodField()
    area_results = serializers.SerializerMethodField()
    domain_results = serializers.SerializerMethodField()

    class Meta:
        model = Evaluation
        fields = [
            "id",
            "patient",
            "patient_name",
            "created_at",
            "evaluated_at",
            "instrument_code",
            "instrument_version",
            "age_band",
            "age_in_months",
            "used_corrected_age",
            "notes",
            "diagnosis",
            "final_status",
            "trace",
            "area_results",
            "domain_results",
            "answers",
        ]

    def get_diagnosis(self, obj):
        summary = getattr(obj, "summary", None)
        return getattr(summary, "diagnosis", None)

    def get_final_status(self, obj):
        summary = getattr(obj, "summary", None)
        return getattr(summary, "final_status", None)

    def get_trace(self, obj):
        summary = getattr(obj, "summary", None)
        return getattr(summary, "trace", None)

    def get_area_results(self, obj):
        return [
            {
                "area": r.area,
                "yes_count": r.yes_count,
                "total_count": r.total_count,
                "status": r.status,
            }
            for r in obj.area_results.all()
        ]

    def get_domain_results(self, obj):
        return [
            {
                "domain": r.domain,
                "count": r.count,
                "red_flags": r.red_flags,
                "status": r.status,
            }
            for r in obj.domain_results.all()
        ]

    def get_answers(self, obj):
        qs = obj.answers.select_related("question").all()
        return [
            {
                "question_id": a.question_id,
                "question_code": a.question.code,
                "question_text": a.question.text,
                "domain": a.question.domain,
                "area": a.question.area,
                "is_critical": a.question.is_critical,
                "from_previous_group": a.from_previous_group,
                "value": a.value_bool,
            }
            for a in qs
        ]


class PatientSerializer(serializers.ModelSerializer):
    evaluations_count = serializers.SerializerMethodField()
    current_age_months = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = [
            "id",
            "full_name",
            "document_id",
            "sex",
            "date_of_birth",
            "phone",
            "gestational_weeks",
            "is_premature",
            "evaluations_count",
            "current_age_months",
            "created_at",
        ]

    def get_evaluations_count(self, obj):
        return obj.evaluations.count()

    def get_current_age_months(self, obj):
        today = timezone.localdate()
        raw = _age_months(obj.date_of_birth, today)
        corrected = _corrected_age_months(
            dob=obj.date_of_birth,
            reference_date=today,
            is_premature=obj.is_premature,
            gestational_weeks=obj.gestational_weeks,
        )
        # misma regla: corregir solo si < 24 meses y es prematuro con semanas
        if obj.is_premature and obj.gestational_weeks and raw < 24:
            return corrected
        return raw
