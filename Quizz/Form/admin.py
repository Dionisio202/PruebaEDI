from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Q

from .models import (
    Patient,
    Evaluation,
    Answer,
    Instrument,
    InstrumentVersion,
    AgeBand,
    Question,
    EvaluationAreaResult,
    EvaluationDomainResult,
    EvaluationSummary,
)


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
    show_change_link = True

    fields = (
        "id",
        "created_at",
        "evaluated_at",
        "age_band",
        "age_in_months",
        "used_corrected_age",
        "instrument_version",
        "final_status",
        "diagnosis",
        "open_evaluation",
    )
    readonly_fields = fields

    def diagnosis(self, obj):
        s = getattr(obj, "summary", None)
        return getattr(s, "diagnosis", "-") if s else "-"
    diagnosis.short_description = "Diagnóstico"

    def final_status(self, obj):
        s = getattr(obj, "summary", None)
        return getattr(s, "final_status", "-") if s else "-"
    final_status.short_description = "Estado final"

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
        "question",
        "question_text",
        "question_domain",
        "question_area",
        "question_is_critical",
        "from_previous_group",
        "value_bool",
    ]
    readonly_fields = fields

    def question_text(self, obj):
        if not obj or not obj.question_id:
            return ""
        q = getattr(obj, "_question_obj", None)
        if q is not None:
            return q.text
        return obj.question.text if obj.question else ""
    question_text.short_description = "Pregunta"

    def question_domain(self, obj):
        q = getattr(obj, "_question_obj", None) or getattr(obj, "question", None)
        return getattr(q, "domain", "")
    question_domain.short_description = "Tipo"

    def question_area(self, obj):
        q = getattr(obj, "_question_obj", None) or getattr(obj, "question", None)
        return getattr(q, "area", "")
    question_area.short_description = "Área"

    def question_is_critical(self, obj):
        q = getattr(obj, "_question_obj", None) or getattr(obj, "question", None)
        return bool(getattr(q, "is_critical", False))
    question_is_critical.short_description = "¿Crítica?"
    question_is_critical.boolean = True


class EvaluationAreaResultInline(admin.TabularInline):
    model = EvaluationAreaResult
    extra = 0
    can_delete = False

    fields = ("area", "yes_count", "total_count", "status")
    readonly_fields = fields


class EvaluationDomainResultInline(admin.TabularInline):
    model = EvaluationDomainResult
    extra = 0
    can_delete = False

    fields = ("domain", "count", "red_flags", "status")
    readonly_fields = fields


class EvaluationSummaryInline(admin.StackedInline):
    model = EvaluationSummary
    extra = 0
    can_delete = False

    fields = (
        "diagnosis",
        "final_status",
        "applied_previous_group",
        "previous_group_result",
        "calculated_at",
        "trace",
    )
    readonly_fields = fields


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

    inlines = [EvaluationInline]

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
        "evaluated_at",
        "age_band",
        "age_in_months",
        "diagnosis",
        "final_status",
        "instrument_version",
        "created_at",
    ]

    list_filter = [
        ("patient", admin.RelatedOnlyFieldListFilter),
        "instrument_version",
        "age_band",
        "used_corrected_age",
        "created_at",
    ]

    search_fields = ["patient__full_name", "patient__document_id"]
    readonly_fields = ["created_at"]

    inlines = [
        EvaluationSummaryInline,
        EvaluationAreaResultInline,
        EvaluationDomainResultInline,
        AnswerInline,
    ]

    fieldsets = (
        ("Paciente", {"fields": ("patient",)}),
        ("Instrumento", {"fields": ("instrument_version",)}),
        ("Edad y Grupo", {"fields": ("evaluated_at", "age_band", "age_in_months", "used_corrected_age")}),
        ("Observaciones", {"fields": ("notes",)}),
        ("Metadata", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def diagnosis(self, obj):
        s = getattr(obj, "summary", None)
        return getattr(s, "diagnosis", "-") if s else "-"
    diagnosis.short_description = "Diagnóstico"

    def final_status(self, obj):
        s = getattr(obj, "summary", None)
        return getattr(s, "final_status", "-") if s else "-"
    final_status.short_description = "Estado final"

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .select_related("patient", "instrument_version", "age_band")
            .select_related("summary")
            .prefetch_related("answers__question")
        )
        return qs


# ===============================
#   ANSWER ADMIN
# ===============================
@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ["evaluation", "question", "question_domain", "question_area", "value_bool", "question_is_critical"]
    list_filter = [
        "value_bool",
        "from_previous_group",
        ("evaluation__patient", admin.RelatedOnlyFieldListFilter),
        "question__domain",
        "question__area",
        "question__is_critical",
    ]
    search_fields = [
        "evaluation__patient__full_name",
        "evaluation__patient__document_id",
        "question__code",
        "question__text",
    ]
    readonly_fields = ["created_at"]

    def question_domain(self, obj):
        return obj.question.domain if obj.question_id else ""
    question_domain.short_description = "Tipo"

    def question_area(self, obj):
        return obj.question.area if obj.question_id else ""
    question_area.short_description = "Área"

    def question_is_critical(self, obj):
        return bool(obj.question.is_critical) if obj.question_id else False
    question_is_critical.short_description = "¿Crítica?"
    question_is_critical.boolean = True


# ===============================
#   Filtro "Paciente" en Preguntas (mantengo tu idea)
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
        # No filtra Question (no hay relación directa). Solo sirve como "puente" para abrir evaluaciones.
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
#   QUESTION ADMIN (reemplaza EDIQuestion)
# ===============================
@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["code", "instrument_version", "age_band", "domain", "area", "is_critical", "display_order"]
    list_filter = ["instrument_version", "age_band", "domain", "area", "is_critical", PatientQuickFilter]
    search_fields = ["code", "text"]
    ordering = ["instrument_version", "age_band", "display_order"]


# ===============================
#   Instrumentos / Versiones / Bandas
# ===============================
@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ["code", "name"]
    search_fields = ["code", "name"]


@admin.register(InstrumentVersion)
class InstrumentVersionAdmin(admin.ModelAdmin):
    list_display = ["instrument", "version", "effective_from", "is_active"]
    list_filter = ["instrument", "is_active"]
    search_fields = ["instrument__code", "instrument__name", "version"]


@admin.register(AgeBand)
class AgeBandAdmin(admin.ModelAdmin):
    list_display = ["instrument_version", "code", "min_months", "max_months"]
    list_filter = ["instrument_version"]
    search_fields = ["instrument_version__instrument__code", "instrument_version__version", "code"]
    ordering = ["instrument_version", "min_months"]


# ===============================
#   Resultados y Resumen (opcionales)
# ===============================
@admin.register(EvaluationAreaResult)
class EvaluationAreaResultAdmin(admin.ModelAdmin):
    list_display = ("evaluation", "area", "yes_count", "total_count", "status")
    list_filter = ("area", "status")
    search_fields = ("evaluation__patient__full_name", "evaluation__patient__document_id")


@admin.register(EvaluationDomainResult)
class EvaluationDomainResultAdmin(admin.ModelAdmin):
    list_display = ("evaluation", "domain", "count", "red_flags", "status")
    list_filter = ("domain", "status")
    search_fields = ("evaluation__patient__full_name", "evaluation__patient__document_id")


@admin.register(EvaluationSummary)
class EvaluationSummaryAdmin(admin.ModelAdmin):
    list_display = ("evaluation", "diagnosis", "final_status", "applied_previous_group", "calculated_at")
    list_filter = ("diagnosis", "final_status", "applied_previous_group")
    search_fields = ("evaluation__patient__full_name", "evaluation__patient__document_id")
    readonly_fields = ("calculated_at",)


# ===============================
#   Precarga para AnswerInline (evitar N+1 en textos)
# ===============================
def _prefetch_questions_for_answers(formset):
    objs = list(getattr(formset, "queryset", []) or [])
    q_ids = [o.question_id for o in objs if o.question_id]
    if not q_ids:
        return
    q_map = {q.id: q for q in Question.objects.filter(id__in=q_ids)}
    for o in objs:
        o._question_obj = q_map.get(o.question_id)


_old_get_formset = AnswerInline.get_formset


def _new_get_formset(self, request, obj=None, **kwargs):
    FormSet = _old_get_formset(self, request, obj, **kwargs)
    old_init = FormSet.__init__

    def __init__(fs_self, *a, **k):
        old_init(fs_self, *a, **k)
        _prefetch_questions_for_answers(fs_self)

    FormSet.__init__ = __init__
    return FormSet


AnswerInline.get_formset = _new_get_formset
