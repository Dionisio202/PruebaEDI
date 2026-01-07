from django.urls import path
from .views import (
    PatientByDocument,
    SubmitEvaluation,
    EvaluationDetail,
    PatientEvaluations,
    PatientList,
    formulario_page,
    resultado_page,
    paciente_historial_page,
    EDIQuestionsByGroup,
)

app_name = "form"

urlpatterns = [
    # ENDPOINTS
    path("submit/", SubmitEvaluation.as_view(), name="submit_evaluation"),
    path("evaluation/<int:evaluation_id>/", EvaluationDetail.as_view(), name="evaluation_detail"),
    path("patient/<int:patient_id>/evaluations/", PatientEvaluations.as_view(), name="patient_evaluations"),
    path("patients/", PatientList.as_view(), name="patient_list"),

    path("questions/", EDIQuestionsByGroup.as_view(), name="questions_by_age_band"),

    path("patient/by-document/", PatientByDocument.as_view(), name="patient_by_document"),

    # PÁGINAS HTML
    path("", formulario_page, name="formulario"),
    path("resultado/<int:evaluation_id>/", resultado_page, name="resultado"),
    path("paciente/<int:patient_id>/historial/", paciente_historial_page, name="paciente_historial"),
]
