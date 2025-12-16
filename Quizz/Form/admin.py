from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.http import HttpResponseRedirect

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
    search_fields = ['evaluation__patient__full_name', 'evaluation__patient__document_id', 'question_code']
    readonly_fields = ['created_at']


# ===============================
#   NUEVO: Filtro "Paciente" en Preguntas
# ===============================
class PatientQuickFilter(admin.SimpleListFilter):
    title = "Paciente (buscar)"
    parameter_name = "patient_id"

    def lookups(self, request, model_admin):
        """
        Muestra una lista corta (máx 20) basada en lo que el usuario haya escrito en el buscador del admin (?q=...)
        Así puedes escribir nombre o documento en la caja de búsqueda del admin,
        y luego te aparecerán pacientes sugeridos en este filtro.
        """
        q = (request.GET.get("q") or "").strip()
        if not q:
            return []

        qs = Patient.objects.filter(
            admin.models.Q(full_name__icontains=q) |
            admin.models.Q(document_id__icontains=q)
        ).order_by("full_name")[:20]

        return [(str(p.id), f"{p.full_name} ({p.document_id})") for p in qs]

    def queryset(self, request, queryset):
        # NO filtramos preguntas por paciente porque no hay relación directa.
        return queryset

    def choices(self, changelist):
        """
        Cuando el usuario elige un paciente, mostramos un link rápido a sus evaluaciones.
        """
        # Deja las opciones por defecto + agregamos link
        for choice in super().choices(changelist):
            yield choice

        patient_id = changelist.get_filters_params().get(self.parameter_name)
        if patient_id:
            try:
                p = Patient.objects.get(pk=patient_id)
                url = (
                    reverse("admin:Form_evaluation_changelist")
                    + f"?patient__id__exact={p.id}"
                )
                yield {
                    "selected": False,
                    "query_string": changelist.get_query_string(remove=[self.parameter_name]),
                    "display": format_html(
                        '<span style="display:block;margin-top:8px;">➡ Ver evaluaciones de <b>{}</b>: '
                        '<a href="{}">Abrir</a></span>',
                        p.full_name, url
                    )
                }
            except Patient.DoesNotExist:
                pass


@admin.register(EDIQuestion)
class EDIQuestionAdmin(admin.ModelAdmin):
    list_display = ['code', 'age_group', 'question_type', 'area', 'is_critical', 'order']
    list_filter = ['age_group', 'question_type', 'area', 'is_critical', PatientQuickFilter]
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
