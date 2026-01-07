from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .serializers import (
    EvaluationCreateSerializer,
    EvaluationDetailSerializer,
    PatientSerializer
)
from .models import (
    Patient,
    Evaluation,
    Instrument,
    InstrumentVersion,
    AgeBand,
    Question,
    EvaluationAreaResult,
    EvaluationDomainResult,
    EvaluationSummary,
)
from .services import get_area_status_display, get_diagnosis_display


AREA_MAP = {
    "Motriz Gruesa": "motriz_gruesa",
    "Motriz Fina": "motriz_fina",
    "Lenguaje": "lenguaje",
    "Social": "social",
    "Conocimiento": "conocimiento",
}


def normalize_area(raw):
    if raw is None:
        return None
    raw = raw.strip()
    return AREA_MAP.get(raw, raw)


# =========================
# API
# =========================

class SubmitEvaluation(APIView):
    """
    API para crear una nueva evaluación EDI.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = EvaluationCreateSerializer(data=request.data)

        if not serializer.is_valid():
            return Response({
                "error": "Datos inválidos",
                "details": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            eval_obj = serializer.save()

            # Tomamos el resumen normalizado (si existe)
            summary = getattr(eval_obj, "summary", None)

            # Resultados por área normalizados
            area_results = {
                r.area: {
                    "yes_count": r.yes_count,
                    "total_count": r.total_count,
                    "status": r.status,
                }
                for r in eval_obj.area_results.all()
            }

            # Resultados por dominio normalizados
            domain_results = {
                r.domain: {
                    "count": r.count,
                    "red_flags": r.red_flags,
                    "status": r.status,
                }
                for r in eval_obj.domain_results.all()
            }

            return Response({
                "success": True,
                "message": "Evaluación creada exitosamente",
                "evaluation_id": eval_obj.id,
                "patient_id": eval_obj.patient.id,
                "patient_name": eval_obj.patient.full_name,
                "instrument_version": str(eval_obj.instrument_version),
                "age_band": eval_obj.age_band.code if eval_obj.age_band_id else None,
                "age_in_months": eval_obj.age_in_months,
                "used_corrected_age": eval_obj.used_corrected_age,
                "results": {
                    "areas": area_results,
                    "domains": domain_results,
                },
                "diagnosis": getattr(summary, "diagnosis", None),
                "final_status": getattr(summary, "final_status", None),
                "diagnosis_display": get_diagnosis_display(getattr(summary, "diagnosis", None)),
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                "error": "Error al procesar la evaluación",
                "details": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EvaluationDetail(APIView):
    """
    API para obtener detalles de una evaluación.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request, evaluation_id):
        evaluation = get_object_or_404(Evaluation, id=evaluation_id)
        serializer = EvaluationDetailSerializer(evaluation)
        return Response(serializer.data)


class PatientEvaluations(APIView):
    """
    API para listar todas las evaluaciones de un paciente.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request, patient_id):
        patient = get_object_or_404(Patient, id=patient_id)
        evaluations = patient.evaluations.all().order_by('-created_at')

        serializer = EvaluationDetailSerializer(evaluations, many=True)

        return Response({
            "patient": PatientSerializer(patient).data,
            "evaluations": serializer.data,
            "total_evaluations": evaluations.count()
        })


class PatientList(APIView):
    """
    API para listar todos los pacientes.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        patients = Patient.objects.all().order_by('-created_at')
        serializer = PatientSerializer(patients, many=True)
        return Response({
            "patients": serializer.data,
            "total": patients.count()
        })


class PatientByDocument(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        document_id = (request.query_params.get("document_id") or "").strip()

        if not document_id:
            return Response(
                {"error": "document_id es requerido"},
                status=status.HTTP_400_BAD_REQUEST
            )

        patient = Patient.objects.filter(document_id=document_id).first()

        if not patient:
            return Response(
                {"found": False, "patient": None},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {"found": True, "patient": PatientSerializer(patient).data},
            status=status.HTTP_200_OK
        )


class EDIQuestionsByGroup(APIView):
    """
    Reemplaza EDIQuestionsByGroup usando AgeBand + Question.
    Acepta:
      - instrument_code (default: EDI)
      - version (opcional; si no, usa la activa)
      - age_band (requerido; antes era age_group)
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        instrument_code = (request.query_params.get("instrument_code") or "EDI").strip()
        version = (request.query_params.get("version") or "").strip()
        age_band_code = (request.query_params.get("age_band") or "").strip()

        if not age_band_code:
            return Response({"error": "age_band es requerido"}, status=status.HTTP_400_BAD_REQUEST)

        instrument = Instrument.objects.filter(code=instrument_code).first()
        if not instrument:
            return Response({"error": f"Instrumento '{instrument_code}' no existe"}, status=status.HTTP_404_NOT_FOUND)

        if version:
            iv = InstrumentVersion.objects.filter(instrument=instrument, version=version).first()
        else:
            iv = (
                InstrumentVersion.objects
                .filter(instrument=instrument, is_active=True)
                .order_by("-effective_from", "-id")
                .first()
            )

        if not iv:
            return Response({"error": "No se encontró una versión del instrumento"}, status=status.HTTP_404_NOT_FOUND)

        band = AgeBand.objects.filter(instrument_version=iv, code=age_band_code).first()
        if not band:
            return Response({"error": f"AgeBand '{age_band_code}' no existe para esa versión"}, status=status.HTTP_404_NOT_FOUND)

        qs = (
            Question.objects
            .filter(instrument_version=iv, age_band=band)
            .order_by("display_order", "id")
        )

        data = [
            {
                "id": q.id,                 # ahora la respuesta se relaciona por FK, no por code string
                "code": q.code,
                "text": q.text,
                "area": q.area,
                "critical": q.is_critical,
                "domain": q.domain,
                "age_band": band.code,
                "display_order": q.display_order,
            }
            for q in qs
        ]
        return Response(data, status=status.HTTP_200_OK)


# =========================
# VISTAS DE TEMPLATES (HTML)
# =========================

@login_required(login_url="/admin/login/")
def formulario_page(request):
    """
    Página del formulario EDI (PROTEGIDA).
    GET /formulario/
    """
    return render(request, "Form/formulario.html")


@login_required(login_url="/admin/login/")
def resultado_page(request, evaluation_id):
    """
    Página de resultados de una evaluación.
    GET /resultado/<id>/
    """
    evaluation = get_object_or_404(Evaluation, id=evaluation_id)
    summary = getattr(evaluation, "summary", None)

    # Construir áreas desde tabla normalizada
    areas = {}
    for r in evaluation.area_results.all():
        # r.area ya viene normalizado tipo "motriz_gruesa"
        # En UI puedes mapear a nombre bonito si quieres, aquí te lo dejo como está.
        areas[r.area] = get_area_status_display(r.status)

    context = {
        "evaluation": evaluation,
        "patient": evaluation.patient,
        "diagnosis_display": get_diagnosis_display(getattr(summary, "diagnosis", None)),
        "final_status": getattr(summary, "final_status", None),
        "areas": areas,
        "domain_results": evaluation.domain_results.all(),
        "summary": summary,
    }

    return render(request, "Form/resultado.html", context)


@login_required(login_url="/admin/login/")
def paciente_historial_page(request, patient_id):
    """
    Página del historial de evaluaciones de un paciente.
    GET /paciente/<id>/historial/
    """
    patient = get_object_or_404(Patient, id=patient_id)
    evaluations = (
        patient.evaluations
        .select_related("instrument_version", "age_band")
        .select_related("summary")
        .order_by("-created_at")
    )

    # Nota: tu nuevo Patient ya no tiene get_age_months/get_corrected_age_months/get_edi_age_group
    # porque el esquema ahora lo calcula el backend/serializer (o lo puedes reponer si quieres).
    # Aquí ponemos valores seguros.
    context = {
        "patient": patient,
        "evaluations": evaluations,
    }

    return render(request, "Form/paciente_historial.html", context)
