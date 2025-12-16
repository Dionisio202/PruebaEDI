from .models import Evaluation, Answer


class EDIEvaluationService:
    """
    Servicio para calcular la evaluación EDI según el PDF
    "FORMATOS APLICACION EDI 12 FEB 2024".

    Corrige:
    - Grupo 1: 1 o 0 en verde => ROJO
    - Grupos 2-7: 1 o 0 en verde => AMARILLO
    - Grupos 8-15: 2-3 en verde => VERDE; 0-1 => AMARILLO
    - Separa Señales de ALERTA (ALE) vs Señales de ALARMA
    - En grupos >=5: FRB/ALE NO modifican calificación global
    """

    GROUPS_CONFIG = {
        1:  {"questions_per_area": 2, "has_frb": True,  "has_previous": False, "frb_affects_global": True,  "ale_affects_global": True},
        2:  {"questions_per_area": 2, "has_frb": True,  "has_previous": True,  "frb_affects_global": True,  "ale_affects_global": True},
        3:  {"questions_per_area": 2, "has_frb": True,  "has_previous": True,  "frb_affects_global": True,  "ale_affects_global": True},
        4:  {"questions_per_area": 2, "has_frb": True,  "has_previous": True,  "frb_affects_global": True,  "ale_affects_global": True},
        5:  {"questions_per_area": 2, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        6:  {"questions_per_area": 2, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        7:  {"questions_per_area": 2, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        8:  {"questions_per_area": 3, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        9:  {"questions_per_area": 3, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        10: {"questions_per_area": 3, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        11: {"questions_per_area": 3, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        12: {"questions_per_area": 3, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        13: {"questions_per_area": 3, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        14: {"questions_per_area": 3, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
        15: {"questions_per_area": 3, "has_frb": False, "has_previous": True,  "frb_affects_global": False, "ale_affects_global": False},
    }

    AREA_FIELDS = {
        "motriz_gruesa": "motriz_gruesa_status",
        "motriz_fina": "motriz_fina_status",
        "lenguaje": "lenguaje_status",
        "social": "social_status",
        "conocimiento": "conocimiento_status",
    }

    def __init__(self, evaluation):
        self.evaluation = evaluation
        self.answers = list(evaluation.answers.all())
        self.age_group = self._get_age_group()
        self.config = self.GROUPS_CONFIG.get(
            self.age_group,
            {"questions_per_area": 2, "has_frb": False, "has_previous": False, "frb_affects_global": False, "ale_affects_global": False},
        )

    # -----------------------------
    # Helpers seguros de atributos
    # -----------------------------
    def _safe_set(self, field, value):
        if hasattr(self.evaluation, field):
            setattr(self.evaluation, field, value)

    def _safe_get(self, field, default=None):
        return getattr(self.evaluation, field, default)

    def _get_age_group(self):
        months = self.evaluation.age_in_months

        if months <= 1:
            return 1
        elif months <= 2:
            return 2
        elif months <= 3:
            return 3
        elif months <= 4:
            return 4
        elif months <= 6:
            return 5
        elif months <= 9:
            return 6
        elif months <= 12:
            return 7
        elif months <= 15:
            return 8
        elif months <= 18:
            return 9
        elif months <= 24:
            return 10
        elif months <= 30:
            return 11
        elif months <= 36:
            return 12
        elif months <= 48:
            return 13
        elif months <= 59:
            return 14
        else:
            return 15

    def calculate_evaluation(self):
        # 1) Áreas
        self._calculate_development_areas()

        # 2) Exploración neurológica
        self._calculate_neurological_exam()

        # 3) Señales de alarma (ALARM) (si existe en el grupo)
        self._calculate_alarm_signals()

        # 4) Señales de alerta (ALERT) (ALE)
        self._calculate_alert_signals()

        # 5) Factores de riesgo biológico (FRB) (grupos 1-4 obligatorio; >=5 opcional/no-global)
        self._calculate_biological_risks()

        # 6) Grupo anterior si corresponde
        if self.config["has_previous"]:
            self._apply_previous_group_if_needed()

        # 7) Diagnóstico final
        self._calculate_final_diagnosis()

        self.evaluation.save()

    # -----------------------------
    # Áreas de desarrollo
    # -----------------------------
    def _calculate_development_areas(self):
        for area_name, field_name in self.AREA_FIELDS.items():
            area_answers = [
                a for a in self.answers
                if a.answer_type == Answer.AnswerType.AREA
                and a.area == area_name
                and not getattr(a, "from_previous_group", False)
            ]

            if not area_answers:
                self._safe_set(field_name, None)
                continue

            yes_count = sum(1 for a in area_answers if a.value is True)
            total = len(area_answers)

            status = self._get_area_status(yes_count, total)
            self._safe_set(field_name, status)

    def _get_area_status(self, yes_count, total):
        if total == 0:
            return None

        # Grupo 1: 2/2 verde, si no rojo
        if self.age_group == 1:
            return Evaluation.Status.GREEN if yes_count == total else Evaluation.Status.RED

        # Grupos 2-7: 2/2 verde, si no amarillo
        if 2 <= self.age_group <= 7:
            return Evaluation.Status.GREEN if yes_count == total else Evaluation.Status.YELLOW

        # Grupos 8-15: (3 items) 2 o 3 verde, si no amarillo
        return Evaluation.Status.GREEN if yes_count >= 2 else Evaluation.Status.YELLOW

    # -----------------------------
    # Exploración neurológica
    # -----------------------------
    def _calculate_neurological_exam(self):
        neuro_answers = [a for a in self.answers if a.answer_type == Answer.AnswerType.NEUROLOGICAL]

        if not neuro_answers:
            self._safe_set("neurological_red_flags", 0)
            self._safe_set("neurological_status", None)
            return

        red_flags = sum(1 for a in neuro_answers if a.value is True)

        self._safe_set("neurological_red_flags", red_flags)
        # Si hay al menos 1 => “ítem en rojo”
        self._safe_set("neurological_status", Evaluation.Status.RED if red_flags > 0 else Evaluation.Status.GREEN)

    # -----------------------------
    # Señales de ALARMA (ALARM)
    # -----------------------------
    def _calculate_alarm_signals(self):
        alarm_answers = [a for a in self.answers if a.answer_type == Answer.AnswerType.ALARM]

        if not alarm_answers:
            self._safe_set("alarm_signals_count", 0)
            self._safe_set("alarm_signals_status", Evaluation.Status.GREEN)
            return

        count = sum(1 for a in alarm_answers if a.value is True)

        self._safe_set("alarm_signals_count", count)
        # En el PDF se evalúa como “señales de alarma en rojo” (si existe al menos una)
        self._safe_set("alarm_signals_status", Evaluation.Status.RED if count > 0 else Evaluation.Status.GREEN)

    # -----------------------------
    # Señales de ALERTA (ALERT) (ALE)
    # -----------------------------
    def _calculate_alert_signals(self):
        # Si tu enum no tiene ALERT todavía, agrégalo en Answer.AnswerType
        alert_answers = [a for a in self.answers if a.answer_type == Answer.AnswerType.ALERT]


        if not alert_answers:
            self._safe_set("alert_signals_count", 0)
            self._safe_set("alert_signals_status", Evaluation.Status.GREEN)
            return

        count = sum(1 for a in alert_answers if a.value is True)

        self._safe_set("alert_signals_count", count)
        # ALE se considera “en amarillo” cuando existe al menos 1 (el conteo se usa en tablas globales 1-4)
        self._safe_set("alert_signals_status", Evaluation.Status.YELLOW if count >= 1 else Evaluation.Status.GREEN)


    # -----------------------------
    # FRB
    # -----------------------------
    def _calculate_biological_risks(self):
        bio_answers = [a for a in self.answers if a.answer_type == Answer.AnswerType.BIOLOGICAL]

        if not bio_answers:
            self._safe_set("biological_risk_count", 0)
            self._safe_set("biological_risk_status", Evaluation.Status.GREEN)
            return

        count = sum(1 for a in bio_answers if a.value is True)

        self._safe_set("biological_risk_count", count)
        # FRB “en amarillo” si hay al menos 1
        self._safe_set("biological_risk_status", Evaluation.Status.YELLOW if count > 0 else Evaluation.Status.GREEN)

    # -----------------------------
    # Grupo anterior
    # -----------------------------
    def _apply_previous_group_if_needed(self):
        needs_previous = False

        for area_name, field_name in self.AREA_FIELDS.items():
            current_status = self._safe_get(field_name)

            if current_status != Evaluation.Status.YELLOW:
                continue

            current_answers = [
                a for a in self.answers
                if a.answer_type == Answer.AnswerType.AREA
                and a.area == area_name
                and not getattr(a, "from_previous_group", False)
            ]
            current_yes = sum(1 for a in current_answers if a.value is True)

            # Solo si logró 0 ítems en el grupo actual
            if current_yes != 0:
                continue

            needs_previous = True

            prev_answers = [
                a for a in self.answers
                if a.answer_type == Answer.AnswerType.AREA
                and a.area == area_name
                and getattr(a, "from_previous_group", False)
            ]
            if not prev_answers:
                # Si no hay respuestas del anterior, no podemos recalificar; se queda amarillo.
                continue

            prev_yes = sum(1 for a in prev_answers if a.value is True)

            # Regla PDF: si obtiene 2+ en amarillo => amarillo; si 0-1 => rojo
            new_status = Evaluation.Status.YELLOW if prev_yes >= 2 else Evaluation.Status.RED
            self._safe_set(field_name, new_status)

        self._safe_set("applied_previous_group", needs_previous)

    # -----------------------------
    # Diagnóstico final
    # -----------------------------
    def _calculate_final_diagnosis(self):
        areas_status = [self._safe_get(f) for f in self.AREA_FIELDS.values()]
        areas_status = [s for s in areas_status if s is not None]

        red_areas = areas_status.count(Evaluation.Status.RED)
        yellow_areas = areas_status.count(Evaluation.Status.YELLOW)

        alarm_status = self._safe_get("alarm_signals_status", Evaluation.Status.GREEN)
        neuro_status = self._safe_get("neurological_status", Evaluation.Status.GREEN)

        has_red_alarm = (alarm_status == Evaluation.Status.RED)
        has_red_neuro = (neuro_status == Evaluation.Status.RED)

        # ---------
        # Grupos >=5: global SOLO depende de áreas + neuro + alarma
        # (FRB y ALE no modifican calificación global)
        # ---------
        if self.age_group >= 5:
            if red_areas >= 1 or has_red_alarm or has_red_neuro:
                self._safe_set("diagnosis", Evaluation.Diagnosis.RISK)
                self._safe_set("final_status", Evaluation.Status.RED)
                return

            if yellow_areas >= 1:
                self._safe_set("diagnosis", Evaluation.Diagnosis.DELAY)
                self._safe_set("final_status", Evaluation.Status.YELLOW)
                return

            self._safe_set("diagnosis", Evaluation.Diagnosis.NORMAL)
            self._safe_set("final_status", Evaluation.Status.GREEN)
            return

        # ---------
        # Grupos 1-4: usar tablas globales con FRB + ALE + áreas + neuro (+ alarma si aplica)
        # ---------
        alert_count = self._safe_get("alert_signals_count", 0)
        bio_count = self._safe_get("biological_risk_count", 0)

        # RIESGO (según tabla): incluye áreas rojas, 2+ áreas amarillas, 1 área amarilla + (FRB o ALE),
        # alarma roja, neuro rojo
        if (
            red_areas >= 1
            or yellow_areas >= 2
            or (yellow_areas >= 1 and (bio_count >= 1 or alert_count >= 1))
            or has_red_alarm
            or has_red_neuro
        ):
            self._safe_set("diagnosis", Evaluation.Diagnosis.RISK)
            self._safe_set("final_status", Evaluation.Status.RED)
            return

        # REZAGO (según tabla): 1 área amarilla, 2+ alertas, 2+ FRB, o mezcla (1+ alerta y 1+ FRB)
        if (
            yellow_areas >= 1
            or alert_count >= 2
            or bio_count >= 2
            or (alert_count >= 1 and bio_count >= 1)
        ):
            self._safe_set("diagnosis", Evaluation.Diagnosis.DELAY)
            self._safe_set("final_status", Evaluation.Status.YELLOW)
            return

        # NORMAL: todo verde o solo 1 FRB o solo 1 alerta (con el resto verde)
        self._safe_set("diagnosis", Evaluation.Diagnosis.NORMAL)
        self._safe_set("final_status", Evaluation.Status.GREEN)


def get_area_status_display(status):
    if status == Evaluation.Status.GREEN:
        return "🟢 Verde - Normal"
    if status == Evaluation.Status.YELLOW:
        return "🟡 Amarillo - Atención"
    if status == Evaluation.Status.RED:
        return "🔴 Rojo - Riesgo"
    return "⚪ No aplica"


def get_diagnosis_display(diagnosis):
    if diagnosis == Evaluation.Diagnosis.NORMAL:
        return "✅ Desarrollo Normal"
    if diagnosis == Evaluation.Diagnosis.DELAY:
        return "⚠️ Rezago en el desarrollo"
    if diagnosis == Evaluation.Diagnosis.RISK:
        return "❌ Riesgo de retraso en el desarrollo"
    return "❓ Sin evaluar"
