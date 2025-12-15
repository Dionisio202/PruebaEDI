from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import render, get_object_or_404
from .serializers import (
    EvaluationCreateSerializer, 
    EvaluationDetailSerializer,
    PatientSerializer
)
from .models import Evaluation, Patient , EDIQuestion
from .services import get_area_status_display, get_diagnosis_display


class SubmitEvaluation(APIView):
    """
    API para crear una nueva evaluación EDI.
    
    POST /api/submit/
    Body: {
        "full_name": "Juan Pérez",
        "document_id": "1234567890",
        "sex": "M",
        "date_of_birth": "2024-06-15",
        "phone": "0987654321",
        "is_premature": false,
        "gestational_weeks": null,
        "age_group": "05-06",
        "use_corrected_age": true,
        "answers": [
            {
                "question_code": "05-06_MG_1",
                "answer_type": "AREA",
                "area": "motriz_gruesa",
                "is_critical": true,
                "value": true
            },
            ...
        ],
        "notes": "Evaluación realizada en consultorio"
    }
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
            
            return Response({
                "success": True,
                "message": "Evaluación creada exitosamente",
                "evaluation_id": eval_obj.id,
                "patient_id": eval_obj.patient.id,
                "patient_name": eval_obj.patient.full_name,
                "age_group": eval_obj.age_group,
                "age_in_months": eval_obj.age_in_months,
                "used_corrected_age": eval_obj.used_corrected_age,
                "results": {
                    "motriz_gruesa": eval_obj.motriz_gruesa_status,
                    "motriz_fina": eval_obj.motriz_fina_status,
                    "lenguaje": eval_obj.lenguaje_status,
                    "social": eval_obj.social_status,
                    "conocimiento": eval_obj.conocimiento_status,
                    "neurological": eval_obj.neurological_status,
                },
                "diagnosis": eval_obj.diagnosis,
                "final_status": eval_obj.final_status,
                "diagnosis_display": get_diagnosis_display(eval_obj.diagnosis),
            }, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response({
                "error": "Error al procesar la evaluación",
                "details": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EvaluationDetail(APIView):
    """
    API para obtener detalles de una evaluación.
    
    GET /api/evaluation/<id>/
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
    
    GET /api/patient/<id>/evaluations/
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
    
    GET /api/patients/
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


# VISTAS DE TEMPLATES (HTML)

def formulario_page(request):
    """
    Página del formulario EDI.
    
    GET /formulario/
    """
    return render(request, "Form/formulario.html")


def resultado_page(request, evaluation_id):
    """
    Página de resultados de una evaluación.
    
    GET /resultado/<id>/
    """
    evaluation = get_object_or_404(Evaluation, id=evaluation_id)
    
    context = {
        'evaluation': evaluation,
        'patient': evaluation.patient,
        'diagnosis_display': get_diagnosis_display(evaluation.diagnosis),
        'areas': {
            'Motriz Gruesa': get_area_status_display(evaluation.motriz_gruesa_status),
            'Motriz Fina': get_area_status_display(evaluation.motriz_fina_status),
            'Lenguaje': get_area_status_display(evaluation.lenguaje_status),
            'Social': get_area_status_display(evaluation.social_status),
            'Conocimiento': get_area_status_display(evaluation.conocimiento_status),
        }
    }
    
    return render(request, "Form/resultado.html", context)


def paciente_historial_page(request, patient_id):
    """
    Página del historial de evaluaciones de un paciente.
    
    GET /paciente/<id>/historial/
    """
    patient = get_object_or_404(Patient, id=patient_id)
    evaluations = patient.evaluations.all().order_by('-created_at')
    
    context = {
        'patient': patient,
        'evaluations': evaluations,
        'current_age_months': patient.get_corrected_age_months() if patient.is_premature else patient.get_age_months(),
        'current_edi_group': patient.get_edi_age_group(),
    }
    
    return render(request, "Form/paciente_historial.html", context)

class EDIQuestionsByGroup(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        age_group = request.query_params.get("age_group")
        if not age_group:
            return Response({"error": "age_group es requerido"}, status=status.HTTP_400_BAD_REQUEST)

        qs = EDIQuestion.objects.filter(age_group=age_group).order_by("order", "id")

        data = [
            {
                "id": q.code,          # 👈 tu frontend usa q.id como code
                "text": q.text,
                "area": q.area,
                "critical": q.is_critical,
                "type": q.question_type,
                "age_group": q.age_group,
                "order": q.order,
            }
            for q in qs
        ]
        return Response(data, status=status.HTTP_200_OK)