"""
Google Sheets Export Integration for DBRecruitAI HR Reports Hub.
Supports extracting tabular report records and creating a new tab in a Google Sheet.
Uses Google Sheets API v4 (Service Account or Webhook) with graceful fallback and mock modes.
"""

import os
import re
import json
import logging
import uuid
import csv
import io
from datetime import datetime
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
import requests

logger = logging.getLogger(__name__)

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
}

MONTH_FULL_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December"
}


def extract_spreadsheet_id(url_or_id):
    """
    Extracts the 44-character Google Spreadsheet ID from a URL or raw string.
    Example input: https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0
    Returns: 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms
    """
    if not url_or_id:
        return ""
    url_or_id = url_or_id.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url_or_id)
    if match:
        return match.group(1)
    # Check if raw valid Google Sheet ID format (standard Google IDs are ~44 chars, or at least 25 alphanumeric/hyphen/underscore)
    if re.match(r"^[a-zA-Z0-9-_]{25,}$", url_or_id):
        return url_or_id
    return ""


def sanitize_sheet_title(name):
    r"""
    Ensures tab name conforms to Google Sheets specifications:
    - Maximum 100 characters
    - Cannot contain: \ / ? * : [ ]
    - Cannot start or end with an apostrophe
    """
    cleaned = re.sub(r"[\\/\?\*\:\[\]]", "-", name)
    cleaned = cleaned.strip("' \t\r\n")
    return cleaned[:100] if cleaned else "Report"


def extract_report_tabular_data(tab_type, params):
    """
    Extracts structured tabular data (headers, rows, metadata) for a given report tab
    and query parameters (month, year, date ranges, category filters).
    """
    from hr.models import AuditLog, CandidateEvaluation
    from jobs.models import Application

    tab_type = (tab_type or "audit").strip().lower()
    selected_month = (params.get("month") or params.get(f"{tab_type}_month") or "").strip()
    selected_year = (params.get("year") or params.get(f"{tab_type}_year") or "").strip()
    date_from = (params.get("date_from") or params.get(f"{tab_type}_date_from") or "").strip()
    date_to = (params.get("date_to") or params.get(f"{tab_type}_date_to") or "").strip()
    date_range = (params.get("date_range") or params.get(f"{tab_type}_date_range") or "").strip()

    month_int = None
    month_name = ""
    month_short = ""
    if selected_month:
        try:
            month_int = int(selected_month)
            month_name = MONTH_FULL_NAMES.get(month_int, "")
            month_short = MONTH_NAMES.get(month_int, "")
        except (ValueError, TypeError):
            pass

    year_str = selected_year or str(timezone.now().year)

    if month_name:
        period_str = f"{month_name} {year_str}"
        tab_period = f"{month_short} {year_str}"
    elif date_from and date_to:
        period_str = f"{date_from} to {date_to}"
        tab_period = f"{date_from[-5:]} - {date_to[-5:]}"
    elif date_range:
        period_str = date_range.title()
        tab_period = date_range.title()
    else:
        period_str = "All Time"
        tab_period = "All Time"

    # =========================================================================
    # TAB 1: AUDIT TRAIL
    # =========================================================================
    if tab_type == "audit":
        report_title = "HR System Audit Trail"
        suggested_tab_name = sanitize_sheet_title(f"Audit - {tab_period}")

        qs = AuditLog.objects.select_related("user").all()

        action = params.get("audit_action", "").strip()
        user_id = params.get("audit_user", "").strip()
        search = params.get("audit_search", "").strip()

        if action:
            qs = qs.filter(action=action)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if month_int:
            qs = qs.filter(timestamp__month=month_int)
        if selected_year:
            try:
                qs = qs.filter(timestamp__year=int(selected_year))
            except (ValueError, TypeError):
                pass
        if date_from:
            qs = qs.filter(timestamp__date__gte=date_from)
        if date_to:
            qs = qs.filter(timestamp__date__lte=date_to)
        if search:
            qs = qs.filter(
                Q(target_repr__icontains=search)
                | Q(details__icontains=search)
                | Q(user_name__icontains=search)
                | Q(ip_address__icontains=search)
                | Q(action_display__icontains=search)
            )

        headers = [
            "Timestamp",
            "HR Operator Name",
            "Details & Description",
        ]

        rows = []
        for log in qs[:500]:
            ts_str = log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else ""
            u_name = log.user_name or (log.user.get_full_name() if log.user else "System")
            details_desc = log.details or log.action_display or log.get_action_display() or ""
            rows.append([
                ts_str,
                u_name,
                details_desc,
            ])

    # =========================================================================
    # TAB 2: CANCELLED (REJECTED APPLICATIONS)
    # =========================================================================
    elif tab_type == "cancelled":
        report_title = "Cancelled & Disqualified Candidates"
        suggested_tab_name = sanitize_sheet_title(f"Cancelled - {tab_period}")

        qs = Application.objects.filter(status="Rejected").select_related("job", "applicant").prefetch_related("interview").order_by("-created_at")

        dept = params.get("cancelled_dept", "").strip()
        job_id = params.get("cancelled_job", "").strip()
        search = params.get("cancelled_search", "").strip()
        phase = params.get("cancelled_phase", "").strip()

        if dept:
            qs = qs.filter(job__department=dept)
        if job_id:
            qs = qs.filter(job_id=job_id)
        if month_int:
            qs = qs.filter(created_at__month=month_int)
        if selected_year:
            try:
                qs = qs.filter(created_at__year=int(selected_year))
            except (ValueError, TypeError):
                pass
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(application_id__icontains=search)
                | Q(email__icontains=search)
                | Q(job__title__icontains=search)
            )

        headers = [
            "Application ID",
            "Candidate Full Name",
            "Email Address",
            "Phone Number",
            "Applied Job Position",
            "Department",
            "AI Match Score (%)",
            "Disqualification Stage",
            "Reason / Notes",
            "Application Date",
        ]

        rows = []
        for app in qs[:500]:
            last_interview = app.interview.order_by("-date", "-time").first()
            if hasattr(app, "evaluation") and app.evaluation:
                stage = "Post-Evaluation"
                notes = app.evaluation.final_decision_notes or app.evaluation.weaknesses_notes or app.evaluation.general_notes or "Did not meet evaluation rubric benchmark."
            elif last_interview:
                stage = "Interview Stage"
                notes = last_interview.notes or "Cancelled or disqualified during interview stage."
            else:
                stage = "Screening Stage"
                notes = app.ai_summary or "Application not selected during resume screening."

            if phase and stage != phase:
                continue

            app_date = app.created_at.strftime("%Y-%m-%d") if app.created_at else ""
            match_score = f"{app.ai_score}%" if getattr(app, "ai_score", None) is not None else "N/A"
            rows.append([
                app.application_id,
                f"{app.first_name} {app.last_name}",
                app.email,
                app.phone or "N/A",
                app.job.title if app.job else "N/A",
                app.job.department if app.job and app.job.department else "General",
                match_score,
                stage,
                notes,
                app_date,
            ])

    # =========================================================================
    # TAB 3: EVALUATED CANDIDATES
    # =========================================================================
    elif tab_type == "evaluations":
        report_title = "Evaluated Candidates Report"
        suggested_tab_name = sanitize_sheet_title(f"Evaluated - {tab_period}")

        qs = CandidateEvaluation.objects.filter(
            status="Completed"
        ).filter(
            Q(final_decision__isnull=True) | Q(final_decision="")
        ).select_related(
            "application__job", "evaluator", "interview"
        ).order_by("-evaluation_date", "-created_at")

        dept = params.get("department", "").strip()
        mode = params.get("mode", "").strip()
        recommendation = params.get("recommendation", "").strip()
        search = params.get("search", "").strip()

        if dept:
            qs = qs.filter(application__job__department=dept)
        if mode:
            qs = qs.filter(interview_mode=mode)
        if recommendation:
            qs = qs.filter(recommendation=recommendation)
        if month_int:
            qs = qs.filter(
                Q(evaluation_date__month=month_int)
                | (Q(evaluation_date__isnull=True) & Q(created_at__month=month_int))
            )
        if selected_year:
            try:
                qs = qs.filter(
                    Q(evaluation_date__year=int(selected_year))
                    | (Q(evaluation_date__isnull=True) & Q(created_at__year=int(selected_year)))
                )
            except (ValueError, TypeError):
                pass
        if date_from:
            qs = qs.filter(
                Q(evaluation_date__gte=date_from)
                | (Q(evaluation_date__isnull=True) & Q(created_at__date__gte=date_from))
            )
        if date_to:
            qs = qs.filter(
                Q(evaluation_date__lte=date_to)
                | (Q(evaluation_date__isnull=True) & Q(created_at__date__lte=date_to))
            )
        if search:
            qs = qs.filter(
                Q(application__first_name__icontains=search)
                | Q(application__last_name__icontains=search)
                | Q(application__application_id__icontains=search)
                | Q(application__job__title__icontains=search)
            )

        headers = [
            "Application ID",
            "Candidate Full Name",
            "Role Applied",
            "Department",
            "Interview Mode",
            "Evaluation Date",
            "Overall Rating (1.0-5.0)",
            "Technical Competence",
            "Communication Skills",
            "Problem Solving",
            "Cultural Fit",
            "Leadership Potential",
            "AI Audio Score",
            "Recommendation",
            "Evaluator Name",
            "Strengths Notes",
            "Weaknesses Notes",
            "General Notes",
        ]

        rows = []
        for ev in qs[:500]:
            app = ev.application
            eval_dt = ev.evaluation_date.strftime("%Y-%m-%d") if ev.evaluation_date else (ev.created_at.strftime("%Y-%m-%d") if ev.created_at else "")
            eval_by = ev.evaluator_name or (ev.evaluator.get_full_name() if ev.evaluator else "HR Staff")
            audio_sc = f"{ev.ai_audio_score}/100" if ev.ai_audio_score else "N/A"
            rows.append([
                app.application_id,
                f"{app.first_name} {app.last_name}",
                app.job.title if app.job else "N/A",
                app.job.department if app.job and app.job.department else "General",
                ev.interview_mode,
                eval_dt,
                str(ev.overall_rating),
                str(ev.technical_competence),
                str(ev.communication_skills),
                str(ev.problem_solving),
                str(ev.cultural_fit),
                str(ev.leadership_potential),
                audio_sc,
                ev.recommendation,
                eval_by,
                ev.strengths_notes,
                ev.weaknesses_notes,
                ev.general_notes,
            ])

    # =========================================================================
    # TAB 4: FINAL DECISIONS
    # =========================================================================
    else:
        report_title = "Candidates with Final Decision"
        suggested_tab_name = sanitize_sheet_title(f"Decisions - {tab_period}")

        outcome = params.get("final_outcome", "").strip()
        dept = params.get("final_dept", "").strip()
        search = params.get("final_search", "").strip()

        if outcome == "Hired":
            qs = Application.objects.filter(
                Q(evaluation__final_decision="Hired") | (Q(status="Hired") & Q(evaluation__final_decision__isnull=True))
            )
        elif outcome == "Not Hired":
            qs = Application.objects.filter(evaluation__final_decision="Not Hired")
        else:
            qs = Application.objects.filter(
                Q(evaluation__final_decision__in=["Hired", "Not Hired"]) | Q(status="Hired")
            )

        qs = qs.select_related("job", "applicant", "evaluation", "evaluation__final_decision_by").order_by("-evaluation__final_decision_date", "-evaluation__updated_at")

        if dept:
            qs = qs.filter(job__department=dept)
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(application_id__icontains=search)
                | Q(email__icontains=search)
                | Q(job__title__icontains=search)
                | Q(evaluation__final_decision_notes__icontains=search)
            )
        if month_int:
            qs = qs.filter(
                Q(evaluation__final_decision_date__month=month_int)
                | (Q(evaluation__final_decision_date__isnull=True) & Q(created_at__month=month_int))
            )
        if selected_year:
            try:
                qs = qs.filter(
                    Q(evaluation__final_decision_date__year=int(selected_year))
                    | (Q(evaluation__final_decision_date__isnull=True) & Q(created_at__year=int(selected_year)))
                )
            except (ValueError, TypeError):
                pass
        if date_from:
            qs = qs.filter(
                Q(evaluation__final_decision_date__date__gte=date_from)
                | (Q(evaluation__final_decision_date__isnull=True) & Q(created_at__date__gte=date_from))
            )
        if date_to:
            qs = qs.filter(
                Q(evaluation__final_decision_date__date__lte=date_to)
                | (Q(evaluation__final_decision_date__isnull=True) & Q(created_at__date__lte=date_to))
            )

        headers = [
            "Application ID",
            "Candidate Full Name",
            "Email Address",
            "Role Applied",
            "Department",
            "Final Determination",
            "Decision Date",
            "Final Decision By",
            "Rationale & Final Notes",
            "Expected Salary",
            "Notice Period",
            "Availability Date",
        ]

        rows = []
        for app in qs[:500]:
            ev = getattr(app, "evaluation", None)
            decision = (ev.final_decision if ev and ev.final_decision else ("Hired" if app.status == "Hired" else "Pending"))
            dec_dt = ""
            if ev and ev.final_decision_date:
                dec_dt = ev.final_decision_date.strftime("%Y-%m-%d %H:%M")
            elif ev and ev.updated_at:
                dec_dt = ev.updated_at.strftime("%Y-%m-%d")

            dec_by = ""
            if ev and ev.final_decision_by:
                dec_by = ev.final_decision_by.get_full_name() or ev.final_decision_by.username
            elif ev and ev.evaluator_name:
                dec_by = ev.evaluator_name

            notes = ev.final_decision_notes if ev else ""
            sal = ev.expected_salary if ev else ""
            notice = ev.notice_period if ev else ""
            avail = ev.availability_date if ev else ""

            rows.append([
                app.application_id,
                f"{app.first_name} {app.last_name}",
                app.email,
                app.job.title if app.job else "N/A",
                app.job.department if app.job and app.job.department else "General",
                decision,
                dec_dt,
                dec_by,
                notes,
                sal,
                notice,
                avail,
            ])

    return {
        "tab_type": tab_type,
        "report_title": report_title,
        "period_str": period_str,
        "suggested_tab_name": suggested_tab_name,
        "headers": headers,
        "rows": rows,
    }


def get_google_auth_token():
    """
    Attempts to generate a Google OAuth2 Bearer token from:
    1. GOOGLE_SERVICE_ACCOUNT_FILE setting or env var.
    2. GOOGLE_SERVICE_ACCOUNT_JSON setting or env var.
    3. Root credentials.json file if present.
    Returns access token string or None.
    """
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request

        sa_file = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", ""))
        sa_json = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""))

        creds = None
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]

        if sa_file and os.path.isfile(sa_file):
            creds = service_account.Credentials.from_service_account_file(sa_file, scopes=scopes)
        elif sa_json:
            try:
                info = json.loads(sa_json)
                creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                logger.warning(f"Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
        elif os.path.isfile("credentials.json"):
            creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=scopes)

        if creds:
            creds.refresh(Request())
            return creds.token
    except Exception as e:
        logger.info(f"Google Sheets Service Account authentication not active: {e}")
    return None


def format_as_tsv(headers, rows, meta_info=None):
    """Formats report data as clean Tab-Separated Values for clipboard pasting into Google Sheets."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    if meta_info:
        table_title = meta_info.get("table_title") or meta_info.get("title", "DBRecruit AI Report")
        if not table_title.startswith("DBRecruit AI"):
            table_title = f"DBRecruit AI - {table_title}"
        writer.writerow([table_title])
        writer.writerow([])
    writer.writerow(headers)
    for row in rows:
        writer.writerow([str(c or "").replace("\t", " ").replace("\r\n", " ").replace("\n", " ") for c in row])
    if meta_info:
        writer.writerow([])
        writer.writerow([
            f"Period: {meta_info.get('period', 'All Time')}",
            f"Generated By: {meta_info.get('generated_by', 'HR Staff')}",
            f"Generated At: {meta_info.get('generated_at', '')}",
            f"Total Records: {len(rows)}"
        ])
    return output.getvalue()


def format_as_csv(headers, rows, meta_info=None):
    """Formats report data as CSV for local file download and import."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=",", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    if meta_info:
        table_title = meta_info.get("table_title") or meta_info.get("title", "DBRecruit AI Report")
        if not table_title.startswith("DBRecruit AI"):
            table_title = f"DBRecruit AI - {table_title}"
        writer.writerow([table_title])
        writer.writerow([])
    writer.writerow(headers)
    for row in rows:
        writer.writerow([str(c or "").replace("\r\n", " ").replace("\n", " ") for c in row])
    if meta_info:
        writer.writerow([])
        writer.writerow([
            f"Period: {meta_info.get('period', 'All Time')}",
            f"Generated By: {meta_info.get('generated_by', 'HR Staff')}",
            f"Generated At: {meta_info.get('generated_at', '')}",
            f"Total Records: {len(rows)}"
        ])
    return output.getvalue()


def create_new_google_spreadsheet(file_title, tab_title, headers, rows, meta_info=None):
    """
    Creates a brand new Google Spreadsheet file on Google Drive / Google Sheets,
    titled `file_title`, with an initial worksheet tab `tab_title`, populated
    with report metadata, column headers, and data rows.
    Does NOT require the user to provide an existing spreadsheet link.
    """
    meta_info = meta_info or {}
    token = get_google_auth_token()
    webhook_url = getattr(settings, "GOOGLE_SHEETS_WEBHOOK_URL", os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", ""))

    report_title = meta_info.get("title", "DBRecruitAI Report")
    period_str = meta_info.get("period", "All Time")
    gen_by = meta_info.get("generated_by", "HR Staff")
    gen_at = meta_info.get("generated_at", timezone.now().strftime("%Y-%m-%d %H:%M:%S"))

    clean_tab_title = sanitize_sheet_title(tab_title) if tab_title else "Report"
    clean_file_title = file_title.strip() if file_title else f"DBRecruit AI - {report_title} ({period_str})"
    table_title = meta_info.get("table_title") or clean_file_title
    if not table_title.startswith("DBRecruit AI") and not meta_info.get("table_title"):
        table_title = f"DBRecruit AI - {table_title}"

    meta_info_with_title = dict(meta_info)
    meta_info_with_title["table_title"] = table_title

    tsv_data = format_as_tsv(headers, rows, meta_info_with_title)
    csv_data = format_as_csv(headers, rows, meta_info_with_title)

    values_payload = [
        [table_title],
        [],  # Spacer row
        headers,  # Header row
    ]
    values_payload.extend(rows)
    values_payload.append([])  # Spacer row
    values_payload.append([
        f"Period: {period_str}",
        f"Generated By: {gen_by}",
        f"Generated At: {gen_at}",
        f"Total Records: {len(rows)}"
    ])

    # 1. OPTION A: Google Sheets API v4 using Service Account Bearer Token
    if token:
        try:
            create_url = "https://sheets.googleapis.com/v4/spreadsheets"
            headers_req = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            body = {
                "properties": {
                    "title": clean_file_title,
                },
                "sheets": [
                    {
                        "properties": {
                            "title": clean_tab_title,
                            "gridProperties": {
                                "rowCount": max(len(values_payload) + 20, 100),
                                "columnCount": max(len(headers) + 4, 26),
                            }
                        }
                    }
                ]
            }
            create_resp = requests.post(create_url, json=body, headers=headers_req, timeout=15)
            if create_resp.status_code == 200:
                sheet_data = create_resp.json()
                spreadsheet_id = sheet_data.get("spreadsheetId")
                spreadsheet_url = sheet_data.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

                # Update values in the created sheet
                val_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/'{clean_tab_title}'!A1?valueInputOption=USER_ENTERED"
                val_body = {
                    "range": f"'{clean_tab_title}'!A1",
                    "majorDimension": "ROWS",
                    "values": values_payload,
                }
                requests.put(val_url, json=val_body, headers=headers_req, timeout=15)

                # Share file so anyone with the link can view/edit
                try:
                    drive_perm_url = f"https://www.googleapis.com/drive/v3/files/{spreadsheet_id}/permissions"
                    requests.post(drive_perm_url, json={"role": "writer", "type": "anyone"}, headers=headers_req, timeout=8)
                except Exception as e:
                    logger.warning(f"Could not update Google Drive file permissions: {e}")

                return {
                    "success": True,
                    "spreadsheet_id": spreadsheet_id,
                    "spreadsheet_url": spreadsheet_url,
                    "file_name": clean_file_title,
                    "tab_name": clean_tab_title,
                    "rows_count": len(rows),
                    "tsv_data": tsv_data,
                    "csv_data": csv_data,
                    "mode": "api_v4_created",
                }
            else:
                err_msg = create_resp.json().get("error", {}).get("message", create_resp.text)
                logger.error(f"Google Sheets API Error on create: {err_msg}")
        except Exception as e:
            logger.error(f"Error calling Google Sheets API create: {e}")

    # 2. OPTION B: Google Apps Script Webhook
    if webhook_url:
        try:
            webhook_payload = {
                "action": "create_spreadsheet",
                "title": clean_file_title,
                "tabName": clean_tab_title,
                "headers": headers,
                "rows": rows,
                "meta": meta_info,
            }
            resp = requests.post(webhook_url, json=webhook_payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "spreadsheet_id": data.get("spreadsheetId", "created"),
                    "spreadsheet_url": data.get("url", f"https://docs.google.com/spreadsheets/d/{data.get('spreadsheetId')}/edit"),
                    "file_name": clean_file_title,
                    "tab_name": clean_tab_title,
                    "rows_count": len(rows),
                    "tsv_data": tsv_data,
                    "csv_data": csv_data,
                    "mode": "webhook_created",
                }
        except Exception as e:
            logger.error(f"Error calling Google Sheets webhook create: {e}")

    # 3. OPTION C: Instant Real Google Sheet via sheets.new + Clipboard + CSV
    # When credentials are not yet configured in local environment, we open a real
    # new Google Sheet at https://sheets.new, auto-download the CSV file, and copy
    # the formatted report table to the user's clipboard for instant Ctrl+V pasting.
    return {
        "success": True,
        "is_mock": True,
        "spreadsheet_id": "new",
        "spreadsheet_url": "https://sheets.new",
        "file_name": clean_file_title,
        "tab_name": clean_tab_title,
        "rows_count": len(rows),
        "tsv_data": tsv_data,
        "csv_data": csv_data,
        "message": f"Opened brand new Google Sheet. Copied {len(rows)} records to clipboard — press Ctrl+V to paste.",
        "mode": "sheets_new_clipboard",
    }


def create_google_sheet_tab(spreadsheet_id, tab_title, headers, rows, meta_info=None):
    """
    Creates a new worksheet tab inside the specified Google Spreadsheet and populates
    it with formatted metadata, column headers, and data rows.
    """
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    if not spreadsheet_id:
        return {
            "success": False,
            "error": "A valid Google Spreadsheet URL or ID is required.",
        }

    meta_info = meta_info or {}
    token = get_google_auth_token()
    webhook_url = getattr(settings, "GOOGLE_SHEETS_WEBHOOK_URL", os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", ""))

    # Construct the values payload to write
    report_title = meta_info.get("title", "DBRecruitAI Report")
    period_str = meta_info.get("period", "All Time")
    gen_by = meta_info.get("generated_by", "HR Staff")
    gen_at = meta_info.get("generated_at", timezone.now().strftime("%Y-%m-%d %H:%M:%S"))

    table_title = meta_info.get("table_title") or f"DBRecruit AI - {report_title} ({period_str})"
    if not table_title.startswith("DBRecruit AI"):
        table_title = f"DBRecruit AI - {table_title}"

    values_payload = [
        [table_title],
        [],  # Spacer row
        headers,  # Header row
    ]
    values_payload.extend(rows)
    values_payload.append([])  # Spacer row
    values_payload.append([
        f"Period: {period_str}",
        f"Generated By: {gen_by}",
        f"Generated At: {gen_at}",
        f"Total Records: {len(rows)}"
    ])

    # 1. OPTION A: Google Sheets API v4 using Service Account Bearer Token
    if token:
        try:
            base_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
            headers_req = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # A. Check existing sheets in the spreadsheet to avoid duplicate tab names
            get_resp = requests.get(f"{base_url}?fields=sheets.properties", headers=headers_req, timeout=12)
            existing_titles = set()
            if get_resp.status_code == 200:
                sheet_data = get_resp.json()
                for s in sheet_data.get("sheets", []):
                    existing_titles.add(s.get("properties", {}).get("title", ""))

            final_title = tab_title
            counter = 2
            while final_title in existing_titles:
                final_title = f"{tab_title} ({counter})"
                counter += 1

            # B. Add the new worksheet tab
            batch_url = f"{base_url}:batchUpdate"
            add_sheet_body = {
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": final_title,
                                "gridProperties": {
                                    "rowCount": max(len(values_payload) + 20, 100),
                                    "columnCount": max(len(headers) + 4, 26),
                                }
                            }
                        }
                    }
                ]
            }
            create_resp = requests.post(batch_url, json=add_sheet_body, headers=headers_req, timeout=12)
            if create_resp.status_code != 200:
                err_msg = create_resp.json().get("error", {}).get("message", create_resp.text)
                return {
                    "success": False,
                    "error": f"Google Sheets API Error: {err_msg}",
                }

            create_data = create_resp.json()
            new_sheet_prop = create_data.get("replies", [{}])[0].get("addSheet", {}).get("properties", {})
            new_sheet_id = new_sheet_prop.get("sheetId", 0)

            # C. Update values in the new sheet
            values_url = f"{base_url}/values/'{final_title}'!A1?valueInputOption=USER_ENTERED"
            val_body = {
                "range": f"'{final_title}'!A1",
                "majorDimension": "ROWS",
                "values": values_payload,
            }
            update_resp = requests.put(values_url, json=val_body, headers=headers_req, timeout=15)

            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={new_sheet_id}"
            return {
                "success": True,
                "spreadsheet_id": spreadsheet_id,
                "tab_name": final_title,
                "tab_id": new_sheet_id,
                "spreadsheet_url": sheet_url,
                "rows_count": len(rows),
                "mode": "api_v4",
            }
        except Exception as e:
            logger.error(f"Error calling Google Sheets API: {e}")
            return {
                "success": False,
                "error": f"Failed to connect to Google Sheets API: {str(e)}",
            }

    # 2. OPTION B: Google Apps Script Webhook (Zero GCP project setup for user)
    if webhook_url:
        try:
            webhook_payload = {
                "spreadsheetId": spreadsheet_id,
                "tabName": tab_title,
                "headers": headers,
                "rows": rows,
                "meta": meta_info,
            }
            resp = requests.post(webhook_url, json=webhook_payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "spreadsheet_id": spreadsheet_id,
                    "tab_name": data.get("tabName", tab_title),
                    "spreadsheet_url": data.get("url", f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"),
                    "rows_count": len(rows),
                    "mode": "webhook",
                }
        except Exception as e:
            logger.error(f"Error calling Google Sheets webhook: {e}")

    # 3. OPTION C: Graceful simulation / development fallback
    # When credentials are not yet configured in local environment, we return
    # the target Google Sheet URL with instructions and formatted row count.
    mock_gid = int(datetime.now().strftime("%f"))
    direct_sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={mock_gid}"
    return {
        "success": True,
        "is_mock": True,
        "spreadsheet_id": spreadsheet_id,
        "tab_name": tab_title,
        "tab_id": mock_gid,
        "spreadsheet_url": direct_sheet_url,
        "rows_count": len(rows),
        "message": f"Successfully formatted {len(rows)} records for new tab '{tab_title}'.",
        "mode": "mock_ready",
    }
