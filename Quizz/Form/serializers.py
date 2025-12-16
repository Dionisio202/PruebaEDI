from rest_framework import serializers

from .models import Patient, Evaluation, Answer
from .services import EDIEvaluationService


# =========================================================
# Normalización de áreas (NO importar desde views)
# =========================================================
AREA_MAP = {
    "Motriz Gruesa": "motriz_gruesa",
    "Motriz Fina": "motriz_fina",
    "Lenguaje": "lenguaje",
    "Social": "social",
    "Conocimiento": "conocimiento",
}

ALLOWED_AREAS = {"motriz_gruesa", "motriz_fina", "lenguaje", "social", "conocimiento"}


def normalize_area(raw):
    if raw is None:
        return None
    raw = str(raw).strip()
    return AREA_MAP.get(raw, raw)


# =========================================================
# Serializers
# =========================================================
class AnswerInputSerializer(serializers.Serializer):
    question_code = serializers.CharField()
    answer_type = serializers.ChoiceField(
        choices=Answer.AnswerType.choices,
        default=Answer.AnswerType.AREA
    )
    area = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_critical = serializers.BooleanField(default=False)
    value = serializers.BooleanField()

    def validate(self, attrs):
        t = attrs.get("answer_type")

        # Normalizar area SIEMPRE (por si llega "Motriz Gruesa")
        area = normalize_area(attrs.get("area"))
        attrs["area"] = area

        # Validar área solo si es una pregunta de tipo AREA
        if t == Answer.AnswerType.AREA:
            if not area or area not in ALLOWED_AREAS:
                raise serializers.ValidationError({
                    "area": f"Área inválida para AREA. Debe ser una de: {sorted(ALLOWED_AREAS)}"
                })

        return attrs



class EvaluationCreateSerializer(serializers.Serializer):
    def validate_document_id(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("El número de documento o historia clínica es obligatorio.")
        return value
    # DATOS DEL PACIENTE
    full_name = serializers.CharField(max_length=150)
    document_id = serializers.CharField(required=True)
    sex = serializers.ChoiceField(
        choices=Patient.Sex.choices,
        required=False,
        allow_null=True
    )
    date_of_birth = serializers.DateField(required=True)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # DATOS DE PREMATURIDAD
    gestational_weeks = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=20,
        max_value=42
    )
    is_premature = serializers.BooleanField(default=False)

    # DATOS DE LA EVALUACIÓN
    age_group = serializers.CharField(max_length=20)
    use_corrected_age = serializers.BooleanField(default=True)
    answers = AnswerInputSerializer(many=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_answers(self, value):
        if not value:
            raise serializers.ValidationError("Debe proporcionar al menos una respuesta")
        return value

    def create(self, validated_data):
        answers_data = validated_data.pop("answers")
        age_group = validated_data.pop("age_group")
        use_corrected_age = validated_data.pop("use_corrected_age", True)
        notes = validated_data.pop("notes", "")

        # Datos del paciente
        patient_data = {
            "full_name": validated_data["full_name"],
            "document_id": validated_data.get("document_id"),
            "sex": validated_data.get("sex"),
            "date_of_birth": validated_data.get("date_of_birth"),
            "phone": validated_data.get("phone"),
            "gestational_weeks": validated_data.get("gestational_weeks"),
            "is_premature": validated_data.get("is_premature", False),
        }

        # Crear o actualizar paciente
        patient, _created = Patient.objects.update_or_create(
            document_id=patient_data["document_id"],
            defaults={k: v for k, v in patient_data.items() if v is not None}
        )


        # Calcular edad (corregida si aplica)
        age_in_months = patient.get_corrected_age_months() if use_corrected_age else patient.get_age_months()

        # Crear evaluación inicial
        evaluation = Evaluation.objects.create(
            patient=patient,
            age_group=age_group,
            age_in_months=age_in_months,
            used_corrected_age=use_corrected_age and patient.is_premature,
            notes=notes,
            diagnosis=Evaluation.Diagnosis.NORMAL,
            final_status=Evaluation.Status.GREEN
        )

        # Guardar respuestas
        for answer_data in answers_data:
            # Aquí 'area' ya viene normalizada por AnswerInputSerializer.validate()
            Answer.objects.create(
                evaluation=evaluation,
                question_code=answer_data["question_code"],
                answer_type=answer_data.get("answer_type", Answer.AnswerType.AREA),
                area=answer_data.get("area"),
                is_critical=answer_data.get("is_critical", False),
                value=answer_data["value"],
                from_previous_group=False
            )

        # Procesar evaluación con el servicio
        service = EDIEvaluationService(evaluation)
        service.calculate_evaluation()

        return evaluation


class EvaluationDetailSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.full_name', read_only=True)
    answers = serializers.SerializerMethodField()

    class Meta:
        model = Evaluation
        fields = [
            'id', 'patient', 'patient_name', 'created_at',
            'age_group', 'age_in_months', 'used_corrected_age',
            'motriz_gruesa_status', 'motriz_fina_status',
            'lenguaje_status', 'social_status', 'conocimiento_status',
            'neurological_status', 'neurological_red_flags',
            'alarm_signals_count', 'alarm_signals_status',
            'alert_signals_count', 'alert_signals_status',
            'biological_risk_count', 'biological_risk_status',
            'applied_previous_group', 'previous_group_result',
            'diagnosis', 'final_status', 'notes', 'answers'
        ]

    def get_answers(self, obj):
        return [
            {
                'question_code': ans.question_code,
                'answer_type': ans.answer_type,
                'area': ans.area,
                'value': ans.value,
                'is_critical': ans.is_critical
            }
            for ans in obj.answers.all()
        ]


class PatientSerializer(serializers.ModelSerializer):
    evaluations_count = serializers.SerializerMethodField()
    current_age_months = serializers.SerializerMethodField()
    current_edi_group = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = [
            'id', 'full_name', 'document_id', 'sex', 'date_of_birth',
            'phone', 'gestational_weeks', 'is_premature',
            'evaluations_count', 'current_age_months', 'current_edi_group',
            'created_at'
        ]

    def get_evaluations_count(self, obj):
        return obj.evaluations.count()

    def get_current_age_months(self, obj):
        return obj.get_corrected_age_months() if obj.is_premature else obj.get_age_months()

    def get_current_edi_group(self, obj):
        return obj.get_edi_age_group()
