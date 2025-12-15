from django.db import models
from datetime import date
from dateutil.relativedelta import relativedelta


class Patient(models.Model):
    class Sex(models.TextChoices):
        M = "M", "Masculino"
        F = "F", "Femenino"
        O = "O", "Otro/No especifica"

    full_name = models.CharField(max_length=150, verbose_name="Nombre completo")
    document_id = models.CharField(max_length=30, blank=True, null=True, verbose_name="Cédula/ID")
    sex = models.CharField(max_length=1, choices=Sex.choices, blank=True, null=True, verbose_name="Sexo")
    date_of_birth = models.DateField(verbose_name="Fecha de nacimiento")
    phone = models.CharField(max_length=30, blank=True, null=True, verbose_name="Teléfono")
    
    # CAMPOS PARA PREMATUROS (importantes en EDI)
    gestational_weeks = models.IntegerField(
        null=True, 
        blank=True,
        verbose_name="Semanas de gestación",
        help_text="Dejar vacío si nació a término (≥37 semanas)"
    )
    is_premature = models.BooleanField(default=False, verbose_name="¿Es prematuro?")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Paciente"
        verbose_name_plural = "Pacientes"
        ordering = ['-created_at']

    def __str__(self):
        return self.full_name
    
    def get_age_months(self, reference_date=None):
        """Calcula edad en meses desde nacimiento"""
        if reference_date is None:
            reference_date = date.today()
        delta = relativedelta(reference_date, self.date_of_birth)
        return delta.years * 12 + delta.months
    
    def get_corrected_age_months(self, reference_date=None):
        """Calcula edad corregida para prematuros (hasta 24 meses)"""
        age_months = self.get_age_months(reference_date)
        
        # Solo corregir si es prematuro y menor de 24 meses
        if self.is_premature and self.gestational_weeks and age_months < 24:
            correction_weeks = 40 - self.gestational_weeks
            correction_months = correction_weeks // 4
            return max(0, age_months - correction_months)
        
        return age_months
    
    def get_edi_age_group(self, use_corrected_age=True, reference_date=None):
        """Determina qué grupo de edad EDI le corresponde"""
        if use_corrected_age:
            months = self.get_corrected_age_months(reference_date)
        else:
            months = self.get_age_months(reference_date)
        
        # Mapeo según documento EDI
        if months < 2:
            return "01"
        elif months < 3:
            return "02"
        elif months < 4:
            return "03"
        elif months < 5:
            return "04"
        elif months < 7:
            return "05-06"
        elif months < 10:
            return "07-09"
        elif months < 13:
            return "10-12"
        elif months < 16:
            return "13-15"
        elif months < 19:
            return "16-18"
        elif months < 25:
            return "19-24"
        elif months < 31:
            return "25-30"
        elif months < 37:
            return "31-36"
        elif months < 49:
            return "37-48"
        elif months < 60:
            return "49-59"
        elif months < 72:
            return "60-71"
        else:
            return None  # Fuera del rango EDI


class Evaluation(models.Model):
    class Status(models.TextChoices):
        GREEN = "GREEN", "Verde"
        YELLOW = "YELLOW", "Amarillo"
        RED = "RED", "Rojo"
    
    class Diagnosis(models.TextChoices):
        NORMAL = "NORMAL", "Desarrollo Normal"
        DELAY = "DELAY", "Rezago en el desarrollo"
        RISK = "RISK", "Riesgo de retraso en el desarrollo"

    patient = models.ForeignKey(
        Patient, 
        on_delete=models.CASCADE, 
        related_name="evaluations",
        verbose_name="Paciente"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de evaluación")
    
    # GRUPO DE EDAD
    age_group = models.CharField(
        max_length=20, 
        verbose_name="Grupo de edad EDI",
        help_text="Ej: 01, 02, 05-06, 07-09"
    )
    age_in_months = models.IntegerField(
        verbose_name="Edad en meses",
        help_text="Edad corregida si aplica"
    )
    used_corrected_age = models.BooleanField(
        default=False,
        verbose_name="¿Se usó edad corregida?"
    )
    
    # RESULTADOS POR ÁREA DE DESARROLLO
    motriz_gruesa_status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        null=True,
        verbose_name="Motriz Gruesa"
    )
    motriz_fina_status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        null=True,
        verbose_name="Motriz Fina"
    )
    lenguaje_status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        null=True,
        verbose_name="Lenguaje"
    )
    social_status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        null=True,
        verbose_name="Social"
    )
    conocimiento_status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        null=True,
        verbose_name="Conocimiento"
    )
    
    # EXPLORACIÓN NEUROLÓGICA
    neurological_status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        null=True,
        verbose_name="Exploración Neurológica"
    )
    neurological_red_flags = models.IntegerField(
        default=0,
        verbose_name="Señales rojas neurológicas"
    )
    
    # SEÑALES DE ALARMA
    alarm_signals_count = models.IntegerField(
        default=0,
        verbose_name="Cantidad de señales de alarma"
    )
    alarm_signals_status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        null=True,
        verbose_name="Estado de señales de alarma"
    )
    
    # FACTORES DE RIESGO BIOLÓGICO (grupos 1-4)
    biological_risk_count = models.IntegerField(
        default=0,
        verbose_name="Cantidad de factores de riesgo"
    )
    biological_risk_status = models.CharField(
        max_length=10, 
        choices=Status.choices, 
        null=True,
        verbose_name="Estado de factores de riesgo"
    )
    
    # ¿APLICÓ PREGUNTAS DEL GRUPO ANTERIOR?
    applied_previous_group = models.BooleanField(
        default=False,
        verbose_name="¿Se aplicaron preguntas del grupo anterior?"
    )
    previous_group_result = models.CharField(
        max_length=10,
        choices=Status.choices,
        null=True,
        blank=True,
        verbose_name="Resultado del grupo anterior"
    )
    
    # DIAGNÓSTICO FINAL
    diagnosis = models.CharField(
        max_length=20,
        choices=Diagnosis.choices,
        verbose_name="Diagnóstico"
    )
    final_status = models.CharField(
        max_length=10,
        choices=Status.choices,
        verbose_name="Estado final"
    )
    
    # OBSERVACIONES
    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones",
        help_text="Comentarios adicionales del evaluador"
    )

    class Meta:
        verbose_name = "Evaluación EDI"
        verbose_name_plural = "Evaluaciones EDI"
        ordering = ['-created_at']

    def __str__(self):
        return f"Eval {self.id} - {self.patient.full_name} - {self.diagnosis}"


class Answer(models.Model):
    class AnswerType(models.TextChoices):
        AREA = "AREA", "Área de Desarrollo"
        NEUROLOGICAL = "NEURO", "Exploración Neurológica"
        ALARM = "ALARM", "Señal de Alarma"
        BIOLOGICAL = "BIO", "Factor de Riesgo Biológico"

    evaluation = models.ForeignKey(
        Evaluation, 
        on_delete=models.CASCADE, 
        related_name="answers",
        verbose_name="Evaluación"
    )
    
    # IDENTIFICACIÓN DE LA PREGUNTA
    question_code = models.CharField(
        max_length=50,
        verbose_name="Código de pregunta",
        help_text="Ej: 01_MG_1, 02_MF_2, 03_NEURO_1"
    )
    answer_type = models.CharField(
        max_length=10,
        choices=AnswerType.choices,
        verbose_name="Tipo de pregunta"
    )
    area = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Área de desarrollo",
        help_text="motriz_gruesa, motriz_fina, lenguaje, social, conocimiento"
    )
    
    # METADATA
    is_critical = models.BooleanField(
        default=False,
        verbose_name="¿Es crítica? (**)",
        help_text="Preguntas marcadas con ** en el documento"
    )
    from_previous_group = models.BooleanField(
        default=False,
        verbose_name="¿Del grupo anterior?"
    )
    
    # RESPUESTA
    value = models.BooleanField(verbose_name="Respuesta (Sí/No)")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Respuesta"
        verbose_name_plural = "Respuestas"
        unique_together = ("evaluation", "question_code")
        ordering = ['question_code']

    def __str__(self):
        return f"{self.question_code}: {'Sí' if self.value else 'No'}"


# OPCIONAL: Modelo para almacenar las preguntas del EDI
class EDIQuestion(models.Model):
    class QuestionType(models.TextChoices):
        AREA = "AREA", "Área de Desarrollo"
        NEUROLOGICAL = "NEURO", "Exploración Neurológica"
        ALARM = "ALARM", "Señal de Alarma"
        BIOLOGICAL = "BIO", "Factor de Riesgo Biológico"
    
    age_group = models.CharField(max_length=20, verbose_name="Grupo de edad")
    code = models.CharField(max_length=50, unique=True, verbose_name="Código único")
    question_type = models.CharField(max_length=10, choices=QuestionType.choices)
    area = models.CharField(max_length=50, null=True, blank=True)
    text = models.TextField(verbose_name="Texto de la pregunta")
    is_critical = models.BooleanField(default=False, verbose_name="¿Es crítica? (**)")
    order = models.IntegerField(default=0, verbose_name="Orden de aparición")
    
    class Meta:
        verbose_name = "Pregunta EDI"
        verbose_name_plural = "Preguntas EDI"
        ordering = ['age_group', 'order']
    
    def __str__(self):
        return f"{self.code}: {self.text[:50]}..."