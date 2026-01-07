from __future__ import annotations

from django.db import transaction

from .models import (
    Evaluation,
    EvaluationAreaResult,
    EvaluationDomainResult,
    EvaluationSummary,
)


class EDIEvaluationService:
    """
    Service EDI adaptado al ESQUEMA NORMALIZADO:
      - Lee respuestas desde Answer(value_bool) + Question(domain/area/is_critical)
      - Escribe resultados en:
          * EvaluationAreaResult (por área)
          * EvaluationDomainResult (por dominio: NEURO/ALARM/ALERT/BIO)
          * EvaluationSummary (diagnóstico final)
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

    AREAS = [
        EvaluationAreaResult.Area.MOTRIZ_GRUESA,
        EvaluationAreaResult.Area.MOTRIZ_FINA,
        EvaluationAreaResult.Area.LENGUAJE,
        EvaluationAreaResult.Area.SOCIAL,
        EvaluationAreaResult.Area.CONOCIMIENTO,
    ]

    def __init__(self, evaluation: Evaluation):
        self.evaluation = evaluation

        # importantísimo: traer question para domain/area
        self.answers = list(
            evaluation.answers.select_related("question").all()
        )

        self.age_group_num = self._get_age_group_num()
        self.config = self.GROUPS_CONFIG.get(
            self.age_group_num,
            {"questions_per_area": 2, "has_frb": False, "has_previous": False, "frb_affects_global": False, "ale_affects_global": False},
        )

    def _get_age_group_num(self) -> int:
        """
        Mantengo tu lógica anterior (por meses) para obtener 1..15.
        Así no dependes de strings tipo "05-06".
        """
        months = int(self.evaluation.age_in_months or 0)

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

    # -----------------------------
    # API principal
    # -----------------------------
    @transaction.atomic
    def calculate_evaluation(self) -> None:
        """
        Recalcula todo (idempotente): borra/rehace resultados normalizados.
        """
        # limpiar resultados previos para recalcular sin duplicar
        self.evaluation.area_results.all().delete()
        self.evaluation.domain_results.all().delete()
        EvaluationSummary.objects.filter(evaluation=self.evaluation).delete()

        # 1) Áreas
        area_status_map, area_counts_map = self._calculate_development_areas()

        # 2) Dominios (NEURO/ALARM/ALERT/BIO)
        domain_info = self._calculate_domains()

        # 3) Grupo anterior si corresponde (puede cambiar status de áreas)
        applied_previous = False
        previous_group_result = None
        if self.config.get("has_previous"):
            applied_previous, previous_group_result, area_status_map, area_counts_map = (
                self._apply_previous_group_if_needed(area_status_map, area_counts_map)
            )

        # 4) Diagnóstico final (usa áreas + dominios + reglas por grupo)
        diagnosis, final_status, trace = self._calculate_final_diagnosis(
            area_status_map=area_status_map,
            domain_info=domain_info,
        )

        # 5) Persistir resultados normalizados
        self._persist_area_results(area_status_map, area_counts_map)
        self._persist_domain_results(domain_info)

        EvaluationSummary.objects.create(
            evaluation=self.evaluation,
            applied_previous_group=applied_previous,
            previous_group_result=previous_group_result,
            diagnosis=diagnosis,
            final_status=final_status,
            trace=trace,
        )

    # -----------------------------
    # Áreas
    # -----------------------------
    def _calculate_development_areas(self):
        """
        Retorna:
          - area_status_map: {area: status}
          - area_counts_map: {area: (yes_count, total_count)}
        """
        status_map = {}
        counts_map = {}

        for area in self.AREAS:
            current_answers = [
                a for a in self.answers
                if a.question.domain == "AREA"
                and a.question.area == area
                and not bool(a.from_previous_group)
            ]

            if not current_answers:
                status_map[area] = None
                counts_map[area] = (0, 0)
                continue

            yes_count = sum(1 for a in current_answers if a.value_bool is True)
            total = len(current_answers)

            status = self._get_area_status(yes_count, total)
            status_map[area] = status
            counts_map[area] = (yes_count, total)

        return status_map, counts_map

    def _get_area_status(self, yes_count: int, total: int):
        if total == 0:
            return None

        # Grupo 1: 2/2 verde, si no rojo
        if self.age_group_num == 1:
            return EvaluationAreaResult.Status.GREEN if yes_count == total else EvaluationAreaResult.Status.RED

        # Grupos 2-7: 2/2 verde, si no amarillo
        if 2 <= self.age_group_num <= 7:
            return EvaluationAreaResult.Status.GREEN if yes_count == total else EvaluationAreaResult.Status.YELLOW

        # Grupos 8-15: (3 items) 2 o 3 verde, si no amarillo
        return EvaluationAreaResult.Status.GREEN if yes_count >= 2 else EvaluationAreaResult.Status.YELLOW

    # -----------------------------
    # Dominios
    # -----------------------------
    def _calculate_domains(self):
        """
        Devuelve dict con:
          NEURO: {count, red_flags, status}
          ALARM: {count, red_flags, status}
          ALERT: {count, red_flags, status}
          BIO:   {count, red_flags, status}
        """
        def _count_yes(domain_code: str) -> int:
            return sum(
                1 for a in self.answers
                if a.question.domain == domain_code and a.value_bool is True
            )

        neuro_yes = _count_yes("NEURO")
        alarm_yes = _count_yes("ALARM")
        alert_yes = _count_yes("ALERT")
        bio_yes = _count_yes("BIO")

        info = {
            "NEURO": {
                "count": 0,
                "red_flags": neuro_yes,
                "status": EvaluationDomainResult.Status.RED if neuro_yes > 0 else EvaluationDomainResult.Status.GREEN,
            },
            "ALARM": {
                "count": alarm_yes,
                "red_flags": 0,
                "status": EvaluationDomainResult.Status.RED if alarm_yes > 0 else EvaluationDomainResult.Status.GREEN,
            },
            "ALERT": {
                "count": alert_yes,
                "red_flags": 0,
                # tu regla: 1+ alerta => amarillo (no rojo)
                "status": EvaluationDomainResult.Status.YELLOW if alert_yes >= 1 else EvaluationDomainResult.Status.GREEN,
            },
            "BIO": {
                "count": bio_yes,
                "red_flags": 0,
                # tu regla: 1+ FRB => amarillo
                "status": EvaluationDomainResult.Status.YELLOW if bio_yes > 0 else EvaluationDomainResult.Status.GREEN,
            }
        }
        return info

    # -----------------------------
    # Grupo anterior
    # -----------------------------
    def _apply_previous_group_if_needed(self, area_status_map, area_counts_map):
        """
        Tu regla:
          Si un área quedó AMARILLO y en el grupo actual logró 0 "sí",
          entonces se usan respuestas from_previous_group de esa área:
            - si prev_yes >= 2 => sigue AMARILLO
            - si prev_yes <= 1 => pasa a ROJO
        """
        applied_previous = False
        worst_prev_result = None  # "YELLOW" o "RED"

        for area in self.AREAS:
            current_status = area_status_map.get(area)
            if current_status != EvaluationAreaResult.Status.YELLOW:
                continue

            current_yes, current_total = area_counts_map.get(area, (0, 0))
            if current_total == 0:
                continue

            # Solo si logró 0 "sí" en el grupo actual
            if current_yes != 0:
                continue

            prev_answers = [
                a for a in self.answers
                if a.question.domain == "AREA"
                and a.question.area == area
                and bool(a.from_previous_group)
            ]
            if not prev_answers:
                continue

            applied_previous = True
            prev_yes = sum(1 for a in prev_answers if a.value_bool is True)

            new_status = EvaluationAreaResult.Status.YELLOW if prev_yes >= 2 else EvaluationAreaResult.Status.RED
            area_status_map[area] = new_status

            # para dejar una pista simple en summary
            if new_status == EvaluationAreaResult.Status.RED:
                worst_prev_result = EvaluationSummary.Status.RED
            elif worst_prev_result is None:
                worst_prev_result = EvaluationSummary.Status.YELLOW

        return applied_previous, worst_prev_result, area_status_map, area_counts_map

    # -----------------------------
    # Diagnóstico final (Summary)
    # -----------------------------
    def _calculate_final_diagnosis(self, area_status_map, domain_info):
        areas_status = [s for s in area_status_map.values() if s is not None]
        red_areas = areas_status.count(EvaluationAreaResult.Status.RED)
        yellow_areas = areas_status.count(EvaluationAreaResult.Status.YELLOW)

        has_red_alarm = (domain_info["ALARM"]["status"] == EvaluationDomainResult.Status.RED)
        has_red_neuro = (domain_info["NEURO"]["status"] == EvaluationDomainResult.Status.RED)

        alert_count = int(domain_info["ALERT"]["count"])
        bio_count = int(domain_info["BIO"]["count"])

        trace = {
            "age_group_num": self.age_group_num,
            "red_areas": red_areas,
            "yellow_areas": yellow_areas,
            "alarm_status": domain_info["ALARM"]["status"],
            "neuro_status": domain_info["NEURO"]["status"],
            "alert_count": alert_count,
            "bio_count": bio_count,
        }

        # Grupos >=5: global SOLO depende de áreas + neuro + alarma
        if self.age_group_num >= 5:
            if red_areas >= 1 or has_red_alarm or has_red_neuro:
                return EvaluationSummary.Diagnosis.RISK, EvaluationSummary.Status.RED, trace

            if yellow_areas >= 1:
                return EvaluationSummary.Diagnosis.DELAY, EvaluationSummary.Status.YELLOW, trace

            return EvaluationSummary.Diagnosis.NORMAL, EvaluationSummary.Status.GREEN, trace

        # Grupos 1-4: reglas con FRB + ALERT + áreas + neuro (+ alarma)
        if (
            red_areas >= 1
            or yellow_areas >= 2
            or (yellow_areas >= 1 and (bio_count >= 1 or alert_count >= 1))
            or has_red_alarm
            or has_red_neuro
        ):
            return EvaluationSummary.Diagnosis.RISK, EvaluationSummary.Status.RED, trace

        if (
            yellow_areas >= 1
            or alert_count >= 2
            or bio_count >= 2
            or (alert_count >= 1 and bio_count >= 1)
        ):
            return EvaluationSummary.Diagnosis.DELAY, EvaluationSummary.Status.YELLOW, trace

        return EvaluationSummary.Diagnosis.NORMAL, EvaluationSummary.Status.GREEN, trace

    # -----------------------------
    # Persistencia resultados
    # -----------------------------
    def _persist_area_results(self, area_status_map, area_counts_map):
        for area, status in area_status_map.items():
            yes_count, total_count = area_counts_map.get(area, (0, 0))
            if status is None and total_count == 0:
                continue
            EvaluationAreaResult.objects.create(
                evaluation=self.evaluation,
                area=area,
                yes_count=yes_count,
                total_count=total_count,
                status=status or EvaluationAreaResult.Status.GREEN,
            )

    def _persist_domain_results(self, domain_info):
        for domain_code, payload in domain_info.items():
            EvaluationDomainResult.objects.create(
                evaluation=self.evaluation,
                domain=domain_code,
                count=int(payload.get("count", 0)),
                red_flags=int(payload.get("red_flags", 0)),
                status=payload.get("status") or EvaluationDomainResult.Status.GREEN,
            )


# Helpers UI (siguen sirviendo)
def get_area_status_display(status: str | None) -> str:
    if status == EvaluationSummary.Status.GREEN:
        return "🟢 Verde - Normal"
    if status == EvaluationSummary.Status.YELLOW:
        return "🟡 Amarillo - Atención"
    if status == EvaluationSummary.Status.RED:
        return "🔴 Rojo - Riesgo"
    return "⚪ No aplica"


def get_diagnosis_display(diagnosis: str | None) -> str:
    if diagnosis == EvaluationSummary.Diagnosis.NORMAL:
        return "✅ Desarrollo Normal"
    if diagnosis == EvaluationSummary.Diagnosis.DELAY:
        return "⚠️ Rezago en el desarrollo"
    if diagnosis == EvaluationSummary.Diagnosis.RISK:
        return "❌ Riesgo de retraso en el desarrollo"
    return "❓ Sin evaluar"
