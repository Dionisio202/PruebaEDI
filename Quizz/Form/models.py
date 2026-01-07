from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Q


class Patient(models.Model):
    class Sex(models.TextChoices):
        M = "M", "Masculino"
        F = "F", "Femenino"
        O = "O", "Otro/No especifica"

    full_name = models.CharField(max_length=150)
    document_id = models.CharField(max_length=30, unique=True)
    sex = models.CharField(max_length=1, choices=Sex.choices, null=True, blank=True)
    date_of_birth = models.DateField()
    phone = models.CharField(max_length=30, null=True, blank=True)

    gestational_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    is_premature = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["document_id"]),
            models.Index(fields=["full_name"]),
        ]

    def __str__(self) -> str:
        return self.full_name


class Instrument(models.Model):
    code = models.CharField(max_length=30, unique=True)  # "EDI"
    name = models.CharField(max_length=120)

    def __str__(self) -> str:
        return self.name


class InstrumentVersion(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="versions")
    version = models.CharField(max_length=30)  # "2024-02-12"
    effective_from = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["instrument", "version"], name="uq_instrument_version")
        ]
        indexes = [
            models.Index(fields=["instrument", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.instrument.code} {self.version}"


class AgeBand(models.Model):
    instrument_version = models.ForeignKey(InstrumentVersion, on_delete=models.PROTECT, related_name="age_bands")
    code = models.CharField(max_length=20)  # "01", "05-06", "07-09"
    min_months = models.PositiveSmallIntegerField()
    max_months = models.PositiveSmallIntegerField()  # inclusivo (según tu lógica)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["instrument_version", "code"], name="uq_ageband_code_per_version"),
        ]
        indexes = [
            models.Index(fields=["instrument_version", "min_months", "max_months"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.min_months}-{self.max_months})"


class Question(models.Model):
    class Domain(models.TextChoices):
        AREA = "AREA", "Área de Desarrollo"
        NEURO = "NEURO", "Exploración Neurológica"
        ALARM = "ALARM", "Señal de Alarma"
        ALERT = "ALERT", "Señal de Alerta"
        BIO = "BIO", "Factor de Riesgo Biológico"

    class Area(models.TextChoices):
        MOTRIZ_GRUESA = "motriz_gruesa", "Motriz Gruesa"
        MOTRIZ_FINA = "motriz_fina", "Motriz Fina"
        LENGUAJE = "lenguaje", "Lenguaje"
        SOCIAL = "social", "Social"
        CONOCIMIENTO = "conocimiento", "Conocimiento"

    instrument_version = models.ForeignKey(InstrumentVersion, on_delete=models.PROTECT, related_name="questions")
    age_band = models.ForeignKey(AgeBand, on_delete=models.PROTECT, related_name="questions")

    code = models.CharField(max_length=50)  # estable por versión
    domain = models.CharField(max_length=10, choices=Domain.choices)
    area = models.CharField(max_length=30, choices=Area.choices, null=True, blank=True)

    text = models.TextField()
    is_critical = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["instrument_version", "code"], name="uq_question_code_per_version"),
        ]
        indexes = [
            models.Index(fields=["instrument_version", "age_band", "display_order"]),
            models.Index(fields=["domain", "area"]),
        ]
        ordering = ["age_band__code", "display_order"]

    def clean(self):
        if self.age_band_id and self.instrument_version_id:
            if self.age_band.instrument_version_id != self.instrument_version_id:
                raise ValidationError("El age_band no pertenece a la instrument_version seleccionada.")

        if self.domain == self.Domain.AREA and not self.area:
            raise ValidationError("Las preguntas de dominio AREA deben tener un área asignada.")
        if self.domain != self.Domain.AREA and self.area:
            raise ValidationError("Solo las preguntas de dominio AREA deben tener área.")

    def __str__(self) -> str:
        return f"{self.code}"


class Evaluation(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="evaluations")

    # ✅ clave para que NO pida default: nullable temporalmente
    instrument_version = models.ForeignKey(
        InstrumentVersion,
        on_delete=models.PROTECT,
        related_name="evaluations",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    evaluated_at = models.DateField(default=timezone.now)

    used_corrected_age = models.BooleanField(default=False)
    age_in_months = models.PositiveSmallIntegerField()

    # ✅ clave para que NO pida default: nullable temporalmente
    age_band = models.ForeignKey(
        AgeBand,
        on_delete=models.PROTECT,
        related_name="evaluations",
        null=True,
        blank=True,
    )

    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["patient", "created_at"]),
            models.Index(fields=["instrument_version", "age_band"]),
        ]

    def clean(self):
        # Si todavía no tiene instrument_version o age_band (por data vieja), no rompas
        if self.age_band_id and self.instrument_version_id:
            if self.age_band.instrument_version_id != self.instrument_version_id:
                raise ValidationError("El age_band no pertenece a la instrument_version seleccionada.")

    def __str__(self) -> str:
        return f"Eval {self.id} - {self.patient.full_name}"


class Answer(models.Model):
    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name="answers")

    # ✅ nullable para que NO pida default al migrar
    question = models.ForeignKey(
        Question,
        on_delete=models.PROTECT,
        related_name="answers",
        null=True,
        blank=True,
    )

    from_previous_group = models.BooleanField(default=False)

    # ✅ default para que NO pida default al migrar
    value_bool = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["evaluation", "question"],
                condition=Q(question__isnull=False),
                name="uq_answer_per_question_not_null",
            ),
        ]
        indexes = [
            models.Index(fields=["evaluation", "question"]),
            models.Index(fields=["question", "from_previous_group"]),
        ]

    def clean(self):
        if not self.question_id or not self.evaluation_id:
            return

        if self.evaluation.instrument_version_id and self.question.instrument_version_id != self.evaluation.instrument_version_id:
            raise ValidationError("La pregunta no pertenece a la misma versión del instrumento que la evaluación.")

        if self.evaluation.age_band_id and self.question.age_band_id != self.evaluation.age_band_id:
            raise ValidationError("La pregunta no pertenece al mismo age_band de la evaluación.")

    def __str__(self) -> str:
        code = self.question.code if self.question_id else "SIN_PREGUNTA"
        return f"{self.evaluation_id} - {code}: {'Sí' if self.value_bool else 'No'}"


class EvaluationAreaResult(models.Model):
    class Status(models.TextChoices):
        GREEN = "GREEN", "Verde"
        YELLOW = "YELLOW", "Amarillo"
        RED = "RED", "Rojo"

    class Area(models.TextChoices):
        MOTRIZ_GRUESA = "motriz_gruesa", "Motriz Gruesa"
        MOTRIZ_FINA = "motriz_fina", "Motriz Fina"
        LENGUAJE = "lenguaje", "Lenguaje"
        SOCIAL = "social", "Social"
        CONOCIMIENTO = "conocimiento", "Conocimiento"

    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name="area_results")
    area = models.CharField(max_length=30, choices=Area.choices)
    yes_count = models.PositiveSmallIntegerField(default=0)
    total_count = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evaluation", "area"], name="uq_area_result_per_eval"),
        ]
        indexes = [
            models.Index(fields=["area", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.evaluation_id} - {self.area}: {self.status}"


class EvaluationDomainResult(models.Model):
    class Status(models.TextChoices):
        GREEN = "GREEN", "Verde"
        YELLOW = "YELLOW", "Amarillo"
        RED = "RED", "Rojo"

    class Domain(models.TextChoices):
        NEURO = "NEURO", "Exploración Neurológica"
        ALARM = "ALARM", "Señal de Alarma"
        ALERT = "ALERT", "Señal de Alerta"
        BIO = "BIO", "Factor de Riesgo Biológico"

    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name="domain_results")
    domain = models.CharField(max_length=10, choices=Domain.choices)

    count = models.PositiveSmallIntegerField(default=0)
    red_flags = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evaluation", "domain"], name="uq_domain_result_per_eval"),
        ]
        indexes = [
            models.Index(fields=["domain", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.evaluation_id} - {self.domain}: {self.status}"


class EvaluationSummary(models.Model):
    class Status(models.TextChoices):
        GREEN = "GREEN", "Verde"
        YELLOW = "YELLOW", "Amarillo"
        RED = "RED", "Rojo"

    class Diagnosis(models.TextChoices):
        NORMAL = "NORMAL", "Desarrollo Normal"
        DELAY = "DELAY", "Rezago en el desarrollo"
        RISK = "RISK", "Riesgo de retraso en el desarrollo"

    evaluation = models.OneToOneField(Evaluation, on_delete=models.CASCADE, related_name="summary")

    applied_previous_group = models.BooleanField(default=False)
    previous_group_result = models.CharField(max_length=10, choices=Status.choices, null=True, blank=True)

    diagnosis = models.CharField(max_length=20, choices=Diagnosis.choices)
    final_status = models.CharField(max_length=10, choices=Status.choices)

    calculated_at = models.DateTimeField(auto_now_add=True)
    trace = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["diagnosis", "final_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.evaluation_id} - {self.diagnosis} ({self.final_status})"
