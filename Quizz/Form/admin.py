from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Q

from .models import Patient, Evaluation, Answer, EDIQuestion


# ===============================
#   Helpers
# ===============================
def admin_change_url(obj):
    """
    Construye el link al change view del admin para un objeto (sin asumir app_label fijo).
    """
    return reverse(
        f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",
        args=[obj.pk]
    )


def admin_changelist_url(model):
    """
    Link al changelist de un model.
    """
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")


# ===============================
#   INLINES
# ===============================
class EvaluationInline(admin.TabularInline):
    """
    Dentro de un Paciente, mostrar sus Evaluaciones para navegar rápido.
    """
    model = Evaluation
    extra = 0
    can_delete = False
    show_change_link = True  # muestra link "Editar" automáticamente

    fields = (
        "id",
        "created_at",
        "age_group",
        "age_in_months",
        "used_corrected_age",
        "diagnosis",
        "final_status",
        "open_evaluation",
    )
    readonly_fields = fields

    def open_evaluation(self, obj):
        if not obj or not obj.pk:
            return "-"
        url = admin_change_url(obj)
        return format_html('<a class="button" href="{}">Abrir</a>', url)
    open_evaluation.short_description = "Ver"


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 0
    can_delete = False

    fields = [
        "question_code",
        "question_text",
        "answer_type",
        "area",
        "is_critical",
        "from_previous_group",
        "value",
    ]
    readonly_fields = fields

    def question_text(self, obj):
        """
        Muestra el texto de la pregunta basado en EDIQuestion.code = Answer.question_code
        """
        if not obj or not obj.question_code:
            return ""
        q = getattr(obj, "_edi_question", None)
        if q is not None:
            return q.text
        return ""
    question_text.short_description = "Pregunta"


# ===============================
#   PATIENT ADMIN
# ===============================
@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = [
        "full_name",
        "document_id",
        "sex",
        "date_of_birth",
        "is_premature",
        "evaluations_count",
        "created_at",
        "open_evaluations",
    ]
    list_filter = ["sex", "is_premature", "created_at"]
    search_fields = ["full_name", "document_id"]
    readonly_fields = ["created_at"]

    inlines = [EvaluationInline]  # ✅ aquí queda el consolidado por paciente

    fieldsets = (
        ("Información Personal", {
            "fields": ("full_name", "document_id", "sex", "date_of_birth", "phone")
        }),
        ("Información de Nacimiento", {
            "fields": ("is_premature", "gestational_weeks"),
            "description": "Datos relevantes para cálculo de edad corregida"
        }),
        ("Metadata", {
            "fields": ("created_at",),
            "classes": ("collapse",)
        })
    )

    def evaluations_count(self, obj):
        return obj.evaluations.count()
    evaluations_count.short_description = "Evaluaciones"

    def open_evaluations(self, obj):
        """
        Link directo para ver el listado de evaluaciones filtrado por este paciente.
        """
        url = admin_changelist_url(Evaluation) + f"?patient__id__exact={obj.id}"
        return format_html('<a href="{}">Ver evaluaciones</a>', url)
    open_evaluations.short_description = "Acción"


# ===============================
#   EVALUATION ADMIN
# ===============================
@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "patient",
        "age_group",
        "age_in_months",
        "final_status",
        "diagnosis",
        "created_at",
    ]

    # ✅ ahora puedes filtrar por paciente desde el listado de evaluaciones
    list_filter = [
        ("patient", admin.RelatedOnlyFieldListFilter),
        "final_status",
        "diagnosis",
        "age_group",
        "used_corrected_age",
        "created_at",
    ]

    search_fields = ["patient__full_name", "patient__document_id"]
    readonly_fields = ["created_at"]
    inlines = [AnswerInline]

    fieldsets = (
        ("Paciente", {
            "fields": ("patient",)
        }),
        ("Edad y Grupo", {
            "fields": ("age_group", "age_in_months", "used_corrected_age")
        }),
        ("Resultados por Área", {
            "fields": (
                "motriz_gruesa_status",
                "motriz_fina_status",
                "lenguaje_status",
                "social_status",
                "conocimiento_status",
            )
        }),
        ("Evaluación Neurológica", {
            "fields": ("neurological_status", "neurological_red_flags")
        }),
        ("Señales de Alarma", {
            "fields": ("alarm_signals_count", "alarm_signals_status")
        }),
        # ✅ faltaban estos en tu fieldsets, pero existen en tu modelo
        ("Señales de Alerta", {
            "fields": ("alert_signals_count", "alert_signals_status")
        }),
        ("Factores de Riesgo Biológico", {
            "fields": ("biological_risk_count", "biological_risk_status")
        }),
        ("Grupo Anterior", {
            "fields": ("applied_previous_group", "previous_group_result"),
            "classes": ("collapse",)
        }),
        ("Diagnóstico Final", {
            "fields": ("diagnosis", "final_status"),
            "classes": ("wide",)
        }),
        ("Observaciones", {
            "fields": ("notes",)
        }),
        ("Metadata", {
            "fields": ("created_at",),
            "classes": ("collapse",)
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editando
            return self.readonly_fields + [
                "motriz_gruesa_status",
                "motriz_fina_status",
                "lenguaje_status",
                "social_status",
                "conocimiento_status",
                "neurological_status",
                "alarm_signals_status",
                "alert_signals_status",
                "biological_risk_status",
                "diagnosis",
                "final_status",
            ]
        return self.readonly_fields

    def get_queryset(self, request):
        """
        Optimización: precargar las EDIQuestion de los Answer para mostrar 'question_text' sin N queries.
        """
        qs = super().get_queryset(request).select_related("patient").prefetch_related("answers")
        return qs


# ===============================
#   ANSWER ADMIN
# ===============================
@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ["evaluation", "question_code", "answer_type", "area", "value", "is_critical"]
    list_filter = ["answer_type", "area", "value", "is_critical", "from_previous_group", ("evaluation__patient", admin.RelatedOnlyFieldListFilter)]
    search_fields = ["evaluation__patient__full_name", "evaluation__patient__document_id", "question_code"]
    readonly_fields = ["created_at"]


# ===============================
#   NUEVO: Filtro "Paciente" en Preguntas (mantengo tu idea, pero corregido)
# ===============================
class PatientQuickFilter(admin.SimpleListFilter):
    title = "Paciente (buscar)"
    parameter_name = "patient_id"

    def lookups(self, request, model_admin):
        q = (request.GET.get("q") or "").strip()
        if not q:
            return []

        qs = Patient.objects.filter(
            Q(full_name__icontains=q) | Q(document_id__icontains=q)
        ).order_by("full_name")[:20]

        return [(str(p.id), f"{p.full_name} ({p.document_id})") for p in qs]

    def queryset(self, request, queryset):
        # No filtra EDIQuestion (no hay relación directa). Solo sirve como "puente" para abrir evaluaciones.
        return queryset

    def choices(self, changelist):
        for choice in super().choices(changelist):
            yield choice

        patient_id = changelist.get_filters_params().get(self.parameter_name)
        if patient_id:
            try:
                p = Patient.objects.get(pk=patient_id)
                url = admin_changelist_url(Evaluation) + f"?patient__id__exact={p.id}"
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


# ===============================
#   EDI QUESTION ADMIN
# ===============================
@admin.register(EDIQuestion)
class EDIQuestionAdmin(admin.ModelAdmin):
    list_display = ["code", "age_group", "question_type", "area", "is_critical", "order"]
    list_filter = ["age_group", "question_type", "area", "is_critical", PatientQuickFilter]
    search_fields = ["code", "text"]
    ordering = ["age_group", "order"]

    fieldsets = (
        ("Identificación", {
            "fields": ("code", "age_group", "question_type", "area")
        }),
        ("Contenido", {
            "fields": ("text",)
        }),
        ("Configuración", {
            "fields": ("is_critical", "order")
        }),
    )


# ===============================
#   Mejorar inline Answer: precargar preguntas (EDIQuestion) por cada Evaluation change view
# ===============================
# Truco: en el change_view del EvaluationAdmin, Django ya trae los inlines,
# pero aquí mejoramos el inline para que tenga el texto sin N queries.
def _prefetch_edi_questions_for_answers(formset):
    objs = list(getattr(formset, "queryset", []) or [])
    codes = [o.question_code for o in objs if o.question_code]
    if not codes:
        return
    q_map = {q.code: q for q in EDIQuestion.objects.filter(code__in=codes)}
    for o in objs:
        o._edi_question = q_map.get(o.question_code)

# Hook sobre el inline: Django llama get_formset, ahí metemos un wrapper al formset.queryset
_old_get_formset = AnswerInline.get_formset
def _new_get_formset(self, request, obj=None, **kwargs):
    FormSet = _old_get_formset(self, request, obj, **kwargs)
    old_init = FormSet.__init__

    def __init__(fs_self, *a, **k):
        old_init(fs_self, *a, **k)
        _prefetch_edi_questions_for_answers(fs_self)

    FormSet.__init__ = __init__
    return FormSet

AnswerInline.get_formset = _new_get_formset
