from django.contrib import admin
from .models import Patient, Evaluation, Answer, EDIQuestion


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'document_id', 'sex', 'date_of_birth', 'is_premature', 'evaluations_count', 'created_at']
    list_filter = ['sex', 'is_premature', 'created_at']
    search_fields = ['full_name', 'document_id']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Información Personal', {
            'fields': ('full_name', 'document_id', 'sex', 'date_of_birth', 'phone')
        }),
        ('Información de Nacimiento', {
            'fields': ('is_premature', 'gestational_weeks'),
            'description': 'Datos relevantes para cálculo de edad corregida'
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )
    
    def evaluations_count(self, obj):
        return obj.evaluations.count()
    evaluations_count.short_description = 'Evaluaciones'


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 0
    fields = ['question_code', 'answer_type', 'area', 'is_critical', 'value']
    readonly_fields = ['created_at']


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'patient', 'age_group', 'age_in_months', 
        'final_status', 'diagnosis', 'created_at'
    ]
    list_filter = [
        'final_status', 'diagnosis', 'age_group', 
        'used_corrected_age', 'created_at'
    ]
    search_fields = ['patient__full_name', 'patient__document_id']
    readonly_fields = ['created_at']
    inlines = [AnswerInline]
    
    fieldsets = (
        ('Paciente', {
            'fields': ('patient',)
        }),
        ('Edad y Grupo', {
            'fields': ('age_group', 'age_in_months', 'used_corrected_age')
        }),
        ('Resultados por Área', {
            'fields': (
                'motriz_gruesa_status', 'motriz_fina_status',
                'lenguaje_status', 'social_status', 'conocimiento_status'
            )
        }),
        ('Evaluación Neurológica', {
            'fields': ('neurological_status', 'neurological_red_flags')
        }),
        ('Señales de Alarma', {
            'fields': ('alarm_signals_count', 'alarm_signals_status')
        }),
        ('Factores de Riesgo Biológico', {
            'fields': ('biological_risk_count', 'biological_risk_status')
        }),
        ('Grupo Anterior', {
            'fields': ('applied_previous_group', 'previous_group_result'),
            'classes': ('collapse',)
        }),
        ('Diagnóstico Final', {
            'fields': ('diagnosis', 'final_status'),
            'classes': ('wide',)
        }),
        ('Observaciones', {
            'fields': ('notes',)
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )
    
    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editando
            return self.readonly_fields + [
                'motriz_gruesa_status', 'motriz_fina_status',
                'lenguaje_status', 'social_status', 'conocimiento_status',
                'neurological_status', 'alarm_signals_status',
                'biological_risk_status', 'diagnosis', 'final_status'
            ]
        return self.readonly_fields


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ['evaluation', 'question_code', 'answer_type', 'area', 'value', 'is_critical']
    list_filter = ['answer_type', 'area', 'value', 'is_critical', 'from_previous_group']
    search_fields = ['evaluation__patient__full_name', 'question_code']
    readonly_fields = ['created_at']


@admin.register(EDIQuestion)
class EDIQuestionAdmin(admin.ModelAdmin):
    list_display = ['code', 'age_group', 'question_type', 'area', 'is_critical', 'order']
    list_filter = ['age_group', 'question_type', 'area', 'is_critical']
    search_fields = ['code', 'text']
    ordering = ['age_group', 'order']
    
    fieldsets = (
        ('Identificación', {
            'fields': ('code', 'age_group', 'question_type', 'area')
        }),
        ('Contenido', {
            'fields': ('text',)
        }),
        ('Configuración', {
            'fields': ('is_critical', 'order')
        })
    )