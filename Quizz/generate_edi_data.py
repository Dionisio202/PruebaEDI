#!/usr/bin/env python3
"""
Generador de datos EDI (compatible con tu payload /api/form/submit/).

✅ Garantiza:
- Responde TODAS las preguntas reales del grupo: GET /api/form/questions/?age_band=XX
- answers == questions (mismo conteo)
- age_group coincide con la edad calculada usando la MISMA lógica (meses completos)

🔥 FIX CLAVE:
Tu backend fija evaluated_at = timezone.now() (hoy). Si haces --post,
el script usa SIEMPRE date.today() para generar DOB/age_group y evitar mismatches.

Opciones útiles:
- --continue-on-error: sigue aunque un POST falle
- --seed: reproducible
"""

from __future__ import annotations

import argparse
import random
import string
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests


# -----------------------------
#  Bandas EDI
# -----------------------------
@dataclass(frozen=True)
class Band:
    code: str
    min_months: int
    max_months: int


BANDS: List[Band] = [
    Band("01", 1, 1),
    Band("02", 2, 2),
    Band("03", 3, 3),
    Band("04", 4, 4),
    Band("05-06", 5, 6),
    Band("07-09", 7, 9),
    Band("10-12", 10, 12),
    Band("13-15", 13, 15),
    Band("16-18", 16, 18),
    Band("19-24", 19, 24),
    Band("25-30", 25, 30),
    Band("31-36", 31, 36),
    Band("37-48", 37, 48),
    Band("49-59", 49, 59),
    Band("60-71", 60, 71),
]
BAND_BY_CODE = {b.code: b for b in BANDS}


def band_from_months(months: int) -> str:
    if months <= 0:
        return ""
    for b in BANDS:
        if b.min_months <= months <= b.max_months:
            return b.code
    return ""


# -----------------------------
#  Helpers fecha (misma idea que tu frontend)
# -----------------------------
def last_day_of_month(y: int, m: int) -> int:
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    return (nxt - timedelta(days=1)).day


def subtract_months(d: date, months: int) -> date:
    y = d.year
    m = d.month - months
    while m <= 0:
        m += 12
        y -= 1
    day = min(d.day, last_day_of_month(y, m))
    return date(y, m, day)


def diff_months(from_date: date, to_date: date) -> int:
    months = (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month)
    if to_date.day < from_date.day:
        months -= 1
    return max(0, months)


# -----------------------------
#  Prematuros: edad corregida
# -----------------------------
def corrected_months(dob: date, eval_date: date, is_premature: bool, gw: Optional[int]) -> int:
    if not is_premature:
        return diff_months(dob, eval_date)

    if gw is None:
        return 0

    # >=37 => a término
    if gw >= 37:
        return diff_months(dob, eval_date)

    weeks_early = 40 - gw
    corrected_dob = dob + timedelta(days=weeks_early * 7)
    return diff_months(corrected_dob, eval_date)


def pick_safe_target_month(band: Band) -> int:
    """
    Evita elegir justo el borde cuando hay rango.
    - Si rango >= 3: elige dentro del "medio"
    - Si rango < 3: elige cualquiera
    """
    span = band.max_months - band.min_months
    if span >= 3:
        return random.randint(band.min_months + 1, band.max_months - 1)
    return random.randint(band.min_months, band.max_months)


def make_dob_for_band(eval_date: date, band: Band, is_premature: bool, gw: Optional[int]) -> date:
    """
    DOB diseñado para NO caer en límites:
    - Usamos día 15 del mes para estabilidad
    """
    target_months = pick_safe_target_month(band)

    # Tomo eval_date pero lo "centro" en día 15 para que el DOB quede estable
    eval_centered = date(eval_date.year, eval_date.month, min(15, last_day_of_month(eval_date.year, eval_date.month)))

    corrected_dob = subtract_months(eval_centered, target_months)
    corrected_dob = date(corrected_dob.year, corrected_dob.month, min(15, last_day_of_month(corrected_dob.year, corrected_dob.month)))

    if not is_premature:
        return corrected_dob

    if gw is None:
        raise ValueError("Prematuro requiere gestational_weeks")

    if gw >= 37:
        return corrected_dob

    weeks_early = 40 - gw
    return corrected_dob - timedelta(days=weeks_early * 7)


# -----------------------------
#  Datos fake (compat Patient)
# -----------------------------
FIRST_NAMES_M = ["Juan", "Luis", "Carlos", "Mateo", "Diego", "Santiago", "David", "Andrés"]
FIRST_NAMES_F = ["María", "Ana", "Sofía", "Valentina", "Camila", "Isabella", "Daniela", "Lucía"]
LAST_NAMES = ["Pérez", "Gómez", "Rodríguez", "Sánchez", "Vargas", "Mendoza", "Ortiz", "Castillo"]


def random_name(sex: str) -> str:
    first = random.choice(FIRST_NAMES_M if sex == "M" else FIRST_NAMES_F)
    return f"{first} {random.choice(LAST_NAMES)} {random.choice(LAST_NAMES)}"


def random_document_id() -> str:
    return "".join(random.choice(string.digits) for _ in range(10))


# -----------------------------
#  API preguntas
# -----------------------------
@dataclass
class Question:
    id: int
    domain: str  # AREA|NEURO|ALARM|ALERT|BIO
    area: Optional[str]


class QuestionClient:
    def __init__(self, base_url: str, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache: Dict[str, List[Question]] = {}

    def get_questions(self, age_band: str) -> List[Question]:
        if age_band in self.cache:
            return self.cache[age_band]

        url = f"{self.base_url}/api/form/questions/?age_band={age_band}"
        r = requests.get(url, timeout=self.timeout)
        r.raise_for_status()
        raw = r.json()

        out: List[Question] = []
        ids: List[int] = []

        for q in raw or []:
            qid = int(q["id"])
            ids.append(qid)
            out.append(
                Question(
                    id=qid,
                    domain=str(q.get("domain") or "").upper(),
                    area=q.get("area"),
                )
            )

        if len(ids) != len(set(ids)):
            raise RuntimeError(f"IDs duplicados en /api/form/questions/?age_band={age_band}")

        self.cache[age_band] = out
        return out


def build_answers(questions: List[Question], target: str, band_code: str) -> List[Dict[str, Any]]:
    """
    target:
      - green: AREA=True, otros=False
      - red: fuerza 1 ALARM/NEURO=True
      - yellow: baja 1 área de desarrollo (NO tocar ALARM/NEURO)
    """
    if target not in {"green", "yellow", "red"}:
        raise ValueError("target inválido")

    values: Dict[int, bool] = {}
    area_map: Dict[str, List[int]] = {}

    # base green
    for q in questions:
        if q.domain == "AREA":
            values[q.id] = True
            if q.area:
                area_map.setdefault(q.area, []).append(q.id)
        else:
            values[q.id] = False

    if target == "red":
        candidates = [q.id for q in questions if q.domain in {"ALARM", "NEURO"}]
        if candidates:
            values[random.choice(candidates)] = True
        else:
            # fallback
            if area_map:
                area = random.choice(list(area_map.keys()))
                for qid in area_map[area]:
                    values[qid] = False

    elif target == "yellow":
        # Evita yellow en banda 01 (por tu comentario original)
        if band_code != "01" and area_map:
            area = random.choice(list(area_map.keys()))
            ids = area_map[area]
            keep_yes = random.choice(ids)
            for qid in ids:
                values[qid] = (qid == keep_yes)

    answers = [{"question_id": qid, "value": bool(v)} for qid, v in values.items()]

    if len(answers) != len(questions):
        raise RuntimeError(
            f"Mismatch answers/questions en banda {band_code}: "
            f"{len(answers)} respuestas vs {len(questions)} preguntas"
        )

    return answers


def post_submit(base_url: str, payload: Dict[str, Any], timeout: int = 30) -> requests.Response:
    url = f"{base_url.rstrip('/')}/api/form/submit/"
    return requests.post(url, json=payload, timeout=timeout)


def pick_target(red_rate: float, yellow_rate: float) -> str:
    r = random.random()
    if r < red_rate:
        return "red"
    if r < red_rate + yellow_rate:
        return "yellow"
    return "green"


# -----------------------------
#  MAIN
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--eval-date", default="2026-01-05", help="YYYY-MM-DD (solo se usa si NO haces --post)")
    ap.add_argument("--patients", type=int, default=500)
    ap.add_argument("--evals-per-patient", type=int, default=1)
    ap.add_argument("--premature-rate", type=float, default=0.10)
    ap.add_argument("--red-rate", type=float, default=0.20)
    ap.add_argument("--yellow-rate", type=float, default=0.20)
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--continue-on-error", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.seed:
        random.seed(args.seed)

    # 🔥 FIX: si vas a postear, usa HOY (porque tu backend evalúa con timezone.now)
    if args.post:
        eval_date = date.today()
        # Solo informativo
        try:
            requested = date.fromisoformat(args.eval_date)
            if requested != eval_date:
                print(f"[INFO] --post activo => usando eval_date = HOY ({eval_date.isoformat()}). Ignorando --eval-date={args.eval_date}")
        except Exception:
            print(f"[INFO] --post activo => usando eval_date = HOY ({eval_date.isoformat()}).")
    else:
        eval_date = date.fromisoformat(args.eval_date)

    qc = QuestionClient(args.base_url)

    # ciclo bandas para cubrir TODO
    band_cycle = [b.code for b in BANDS]
    random.shuffle(band_cycle)

    # pool pacientes
    patient_pool: List[Dict[str, Any]] = []
    for i in range(args.patients):
        sex = random.choice(["M", "F"])
        is_prem = random.random() < args.premature_rate
        gw = random.randint(28, 36) if is_prem else None

        desired_band_code = band_cycle[i % len(band_cycle)]
        band = BAND_BY_CODE[desired_band_code]

        dob = make_dob_for_band(eval_date, band, is_prem, gw)

        # Validación dura contra eval_date REAL usado
        cm = corrected_months(dob, eval_date, is_prem, gw)
        computed_band = band_from_months(cm)
        if computed_band != desired_band_code:
            # reintenta 2 veces (con día centrado rara vez falla, pero por prematuros puede)
            ok = False
            for _ in range(2):
                dob = make_dob_for_band(eval_date, band, is_prem, gw)
                cm = corrected_months(dob, eval_date, is_prem, gw)
                if band_from_months(cm) == desired_band_code:
                    ok = True
                    break
            if not ok:
                # si no cuadra, fuerza no prematuro
                is_prem = False
                gw = None
                dob = make_dob_for_band(eval_date, band, is_prem, gw)
                cm = corrected_months(dob, eval_date, is_prem, gw)
                if band_from_months(cm) != desired_band_code:
                    continue  # salta este paciente

        patient_pool.append(
            {
                "full_name": random_name(sex),
                "document_id": random_document_id(),
                "sex": sex,
                "phone": None,
                "date_of_birth": dob,
                "is_premature": is_prem,
                "gestational_weeks": gw,
            }
        )

    created = 0
    ok_posts = 0
    fail_posts = 0

    for p in patient_pool:
        for _ in range(max(1, args.evals_per_patient)):
            cm = corrected_months(p["date_of_birth"], eval_date, p["is_premature"], p["gestational_weeks"])
            band_code = band_from_months(cm)
            if not band_code:
                continue

            questions = qc.get_questions(band_code)
            target = pick_target(args.red_rate, args.yellow_rate)
            answers = build_answers(questions, target, band_code)

            payload: Dict[str, Any] = {
                "full_name": p["full_name"],
                "document_id": p["document_id"],
                "phone": p["phone"],
                "sex": p["sex"],
                "date_of_birth": p["date_of_birth"].isoformat(),

                "age_group": band_code,
                "is_premature": bool(p["is_premature"]),
                "gestational_weeks": int(p["gestational_weeks"]) if p["gestational_weeks"] is not None else None,

                "answers": answers,
            }

            created += 1

            if args.post:
                r = post_submit(args.base_url, payload)
                if r.ok:
                    ok_posts += 1
                else:
                    fail_posts += 1
                    msg = r.text[:900]
                    print(f"[FAIL] {r.status_code}: {msg}")

                    if not args.continue_on_error:
                        raise RuntimeError(f"POST {args.base_url}/api/form/submit/ -> {r.status_code}: {msg}")

    print(f"OK: payloads generados: {created}")
    if args.post:
        print(f"POST OK: {ok_posts} | POST FAIL: {fail_posts}")


if __name__ == "__main__":
    main()
