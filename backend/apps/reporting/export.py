"""Renders one (columns, rows) table into any of the PRD's three export
formats (Module 23: CSV / Excel / PDF). Rows are lists of plain strings —
callers (services.py) have already formatted dates/Decimals, so this module
has no domain knowledge of what it's rendering."""
import csv
from io import BytesIO, StringIO

from django.http import HttpResponse
from django.template.loader import render_to_string
from openpyxl import Workbook
from weasyprint import HTML

FORMATS = ('csv', 'xlsx', 'pdf')


def _csv_response(filename, columns, rows):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    response = HttpResponse(buffer.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    return response


def _xlsx_response(filename, columns, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
    return response


def _pdf_response(filename, title, columns, rows):
    html = render_to_string('reporting/export.html', {'title': title, 'columns': columns, 'rows': rows})
    response = HttpResponse(HTML(string=html).write_pdf(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
    return response


def render_export(*, format, filename, title, columns, rows):
    if format == 'xlsx':
        return _xlsx_response(filename, columns, rows)
    if format == 'pdf':
        return _pdf_response(filename, title, columns, rows)
    return _csv_response(filename, columns, rows)
