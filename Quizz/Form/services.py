from .models import Evaluation, Answer


class EDIEvaluationService:
    """
    Servicio para calcular la evaluación EDI según las reglas del documento.
    """
    
    def __init__(self, evaluation):
        self.evaluation = evaluation
        self.answers = list(evaluation.answers.all())
    
    def calculate_evaluation(self):
        """Calcula todos los resultados de la evaluación"""
        # 1. Calcular estado por cada área de desarrollo
        self._calculate_development_areas()
        
        # 2. Calcular exploración neurológica
        self._calculate_neurological_exam()
        
        # 3. Calcular señales de alarma
        self._calculate_alarm_signals()
        
        # 4. Calcular factores de riesgo biológico (grupos 1-4)
        self._calculate_biological_risks()
        
        # 5. Determinar si necesita aplicar grupo anterior
        self._check_previous_group()
        
        # 6. Calcular diagnóstico final
        self._calculate_final_diagnosis()
        
        self.evaluation.save()
    
    def _calculate_development_areas(self):
        """
        Calcula el estado (Verde/Amarillo/Rojo) por cada área de desarrollo.
        
        Regla EDI:
        - 2 respuestas correctas (Sí) = VERDE
        - 1 o 0 respuestas correctas = AMARILLO
        """
        areas = {
            'motriz_gruesa': 'motriz_gruesa_status',
            'motriz_fina': 'motriz_fina_status',
            'lenguaje': 'lenguaje_status',
            'social': 'social_status',
            'conocimiento': 'conocimiento_status'
        }
        
        for area_name, field_name in areas.items():
            area_answers = [
                a for a in self.answers 
                if a.answer_type == Answer.AnswerType.AREA and a.area == area_name
            ]
            
            if not area_answers:
                # Área no aplica para este grupo
                setattr(self.evaluation, field_name, None)
                continue
            
            # Contar respuestas "Sí" (True)
            yes_count = sum(1 for a in area_answers if a.value is True)
            
            # Aplicar regla EDI
            if yes_count >= 2:
                status = Evaluation.Status.GREEN
            else:
                status = Evaluation.Status.YELLOW
            
            setattr(self.evaluation, field_name, status)
    
    def _calculate_neurological_exam(self):
        """
        Calcula exploración neurológica.
        
        Regla EDI:
        - Cualquier respuesta "Sí" en estas preguntas = ROJO
        - Todas "No" = VERDE
        """
        neuro_answers = [
            a for a in self.answers 
            if a.answer_type == Answer.AnswerType.NEUROLOGICAL
        ]
        
        if not neuro_answers:
            self.evaluation.neurological_status = None
            self.evaluation.neurological_red_flags = 0
            return
        
        # Contar "Sí" (son señales negativas)
        red_flags = sum(1 for a in neuro_answers if a.value is True)
        
        self.evaluation.neurological_red_flags = red_flags
        self.evaluation.neurological_status = (
            Evaluation.Status.RED if red_flags > 0 
            else Evaluation.Status.GREEN
        )
    
    def _calculate_alarm_signals(self):
        """
        Calcula señales de alarma.
        
        Regla EDI:
        - Respuestas "Sí" son señales de alarma (negativas)
        """
        alarm_answers = [
            a for a in self.answers 
            if a.answer_type == Answer.AnswerType.ALARM
        ]
        
        if not alarm_answers:
            self.evaluation.alarm_signals_count = 0
            self.evaluation.alarm_signals_status = Evaluation.Status.GREEN
            return
        
        # Contar "Sí" (son alarmas)
        alarm_count = sum(1 for a in alarm_answers if a.value is True)
        
        self.evaluation.alarm_signals_count = alarm_count
        
        # Estado: cualquier alarma es preocupante
        if alarm_count > 0:
            self.evaluation.alarm_signals_status = Evaluation.Status.RED
        else:
            self.evaluation.alarm_signals_status = Evaluation.Status.GREEN
    
    def _calculate_biological_risks(self):
        """
        Calcula factores de riesgo biológico (solo grupos 1-4).
        
        Regla EDI:
        - Respuestas "Sí" son factores de riesgo
        """
        bio_answers = [
            a for a in self.answers 
            if a.answer_type == Answer.AnswerType.BIOLOGICAL
        ]
        
        if not bio_answers:
            self.evaluation.biological_risk_count = 0
            self.evaluation.biological_risk_status = Evaluation.Status.GREEN
            return
        
        # Contar "Sí" (son riesgos)
        risk_count = sum(1 for a in bio_answers if a.value is True)
        
        self.evaluation.biological_risk_count = risk_count
        
        # Estado basado en cantidad
        if risk_count >= 2:
            self.evaluation.biological_risk_status = Evaluation.Status.YELLOW
        elif risk_count == 1:
            self.evaluation.biological_risk_status = Evaluation.Status.YELLOW
        else:
            self.evaluation.biological_risk_status = Evaluation.Status.GREEN
    
    def _check_previous_group(self):
        """
        Determina si se necesita aplicar preguntas del grupo anterior.
        
        Regla EDI:
        - Si un área sale AMARILLO y no logró ninguna pregunta → aplicar grupo anterior
        """
        areas_status = [
            self.evaluation.motriz_gruesa_status,
            self.evaluation.motriz_fina_status,
            self.evaluation.lenguaje_status,
            self.evaluation.social_status,
            self.evaluation.conocimiento_status
        ]
        
        # Verificar si hay áreas en amarillo
        has_yellow = Evaluation.Status.YELLOW in areas_status
        
        if has_yellow:
            # En una implementación completa, aquí verificarías
            # si respondió 0/2 preguntas correctas
            self.evaluation.applied_previous_group = True
            # previous_group_result se calcularía con las respuestas del grupo anterior
        else:
            self.evaluation.applied_previous_group = False
    
    def _calculate_final_diagnosis(self):
        """
        Calcula el diagnóstico final según las reglas EDI.
        
        RIESGO (ROJO):
        - 1+ áreas en rojo
        - 1+ señales de alarma en rojo
        - Exploración neurológica en rojo
        
        REZAGO (AMARILLO):
        - 1+ áreas en amarillo
        - 2+ señales de alerta en amarillo
        - 2+ factores de riesgo en amarillo
        - 1+ señal de alerta + 1+ factor de riesgo
        
        NORMAL (VERDE):
        - Todo verde o solo 1 factor de riesgo/señal de alerta
        """
        
        # Recopilar todos los estados
        areas_status = [
            self.evaluation.motriz_gruesa_status,
            self.evaluation.motriz_fina_status,
            self.evaluation.lenguaje_status,
            self.evaluation.social_status,
            self.evaluation.conocimiento_status
        ]
        
        # Filtrar None (áreas que no aplican)
        areas_status = [s for s in areas_status if s is not None]
        
        # CRITERIOS DE RIESGO (más severo)
        has_red_area = Evaluation.Status.RED in areas_status
        has_red_alarm = (
            self.evaluation.alarm_signals_status == Evaluation.Status.RED
        )
        has_red_neuro = (
            self.evaluation.neurological_status == Evaluation.Status.RED
        )
        
        if has_red_area or has_red_alarm or has_red_neuro:
            self.evaluation.diagnosis = Evaluation.Diagnosis.RISK
            self.evaluation.final_status = Evaluation.Status.RED
            return
        
        # CRITERIOS DE REZAGO
        has_yellow_area = Evaluation.Status.YELLOW in areas_status
        yellow_alarms = self.evaluation.alarm_signals_count >= 2
        yellow_bio_risks = self.evaluation.biological_risk_count >= 2
        has_mixed_yellow = (
            self.evaluation.alarm_signals_count >= 1 and 
            self.evaluation.biological_risk_count >= 1
        )
        
        if has_yellow_area or yellow_alarms or yellow_bio_risks or has_mixed_yellow:
            self.evaluation.diagnosis = Evaluation.Diagnosis.DELAY
            self.evaluation.final_status = Evaluation.Status.YELLOW
            return
        
        # DESARROLLO NORMAL
        self.evaluation.diagnosis = Evaluation.Diagnosis.NORMAL
        self.evaluation.final_status = Evaluation.Status.GREEN


def get_area_status_display(status):
    """Helper para mostrar el estado en español con emojis"""
    if status == Evaluation.Status.GREEN:
        return "🟢 Verde - Normal"
    elif status == Evaluation.Status.YELLOW:
        return "🟡 Amarillo - Atención"
    elif status == Evaluation.Status.RED:
        return "🔴 Rojo - Riesgo"
    return "⚪ No aplica"


def get_diagnosis_display(diagnosis):
    """Helper para mostrar el diagnóstico con formato"""
    if diagnosis == Evaluation.Diagnosis.NORMAL:
        return "✅ Desarrollo Normal"
    elif diagnosis == Evaluation.Diagnosis.DELAY:
        return "⚠️ Rezago en el desarrollo"
    elif diagnosis == Evaluation.Diagnosis.RISK:
        return "❌ Riesgo de retraso en el desarrollo"
    return "❓ Sin evaluar"