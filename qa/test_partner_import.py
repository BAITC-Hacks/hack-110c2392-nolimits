"""Small partner-layout ZIP fixtures; no original commercial data is committed."""
from io import BytesIO
import zipfile

import pandas as pd
import pytest
from openpyxl import Workbook

from app.services.partner_import import parse_partner_archive


def xlsx(headers, rows, prefix=None):
    book = Workbook()
    sheet = book.active
    for row in prefix or []:
        sheet.append(row)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    target = BytesIO()
    book.save(target)
    book.close()
    return target.getvalue()


def partner_zip(brand='Systeme', *, other_warehouse=False, duplicate_sales_file=False, unknown_policy=False):
    """The same Russian column aliases and six workbook purposes as inputs."""
    internal_a, internal_b = '00000123', '00000987'
    files = {
        f'{brand} Динамика продаж.xlsx': xlsx(
            ['Дата', 'Номер', 'Документ', 'Код', 'Номенклатура', 'Ед.', 'Склад', 'Количество'],
            [['20.09.2026', 'DOC-1', 'Продажа', internal_a, 'Product A', 'шт', 'WH-A', 5],
             ['22.09.2026', 'DOC-2', 'Возврат', internal_a, 'Product A', 'шт', 'WH-A', -1],
             ['22.09.2026', 'DOC-3', 'Продажа', internal_b, 'Product B', 'м', 'WH-B' if other_warehouse else 'WH-A', 8],
             [None, None, 'Итого', None, None, None, None, 12]],
            prefix=[['Sales report'], []]),
        f'{brand} Ежемесячные остатки.xlsx': xlsx(
            ['Номенклатура.Код', 'Номенклатура', 'авг. 2026', 'сент. 2026', 'окт. 2026'],
            [[internal_a, 'Product A', 20, 15, 900], [internal_b, 'Product B', 40, 30, 900]]),
        f'{brand} Ежемесячные продажи.xlsx': xlsx(
            ['Номенклатура.Код', 'Номенклатура', 'сент. 2026'], [[internal_a, 'Product A', 1000000]]),
        f'{brand} Сезонность.xlsx': xlsx(['Месяц', 'Коэффициент'], [['Январь', 1.2]]),
    }
    if brand == 'Systeme':
        files[f'{brand} MOQ.xlsx'] = xlsx(
            ['№', 'Номенклатура', 'Номенклатура.Код', 'Артикул', 'Кратность'],
            [[1, 'Product A', internal_a, 'VENDOR-A', '#N/A' if unknown_policy else 12], [2, 'Product B', internal_b, 'VENDOR-B', .25]])
        files[f'{brand} Товары в пути 22.09.2026.xlsx'] = xlsx(
            ['№', 'Артикул поставщика', 'Код 1с', 'Наименование', 'Свободный остаток', 'СЭ в пути 25.09', 'В пути'],
            [[1, 'VENDOR-A', internal_a, 'Product A', 9, 7, 3]])
    else:
        files[f'{brand} MOQ.xlsx'] = xlsx(
            ['№', 'Код 1с', 'Артикул поставщика', 'Наименование', 'Мин. разр. к отгр.'],
            [[1, internal_a, 'VENDOR-A', 'Product A', '#N/A' if unknown_policy else 24], [2, internal_b, 'VENDOR-B', 'Product B', .5]])
        files[f'{brand} Товары в пути.xlsx'] = xlsx(
            ['Код 1с', 'Артикул ИЭК', ' Наименование', 'РФ УТ-0000 от 1 сентября 2026 г. (поступление до 25.09.2026)', 'В пути'],
            [[internal_a, 'VENDOR-A', 'Product A', 7, 3]])
    if duplicate_sales_file:
        files[f'{brand} Динамика duplicate.xlsx'] = files[f'{brand} Динамика продаж.xlsx']
    target = BytesIO()
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return target.getvalue()


@pytest.mark.parametrize('brand', ['Systeme', 'IEK'])
def test_partner_archive_preserves_codes_provenance_returns_and_source_counts(brand):
    data, report = parse_partner_archive(partner_zip(brand), f'{brand}.zip', 14)
    assert report['errors'] == []
    assert len(report['files']) == 6
    assert len(data['sales']) == report['metrics']['source_dated_sales'] == 3
    assert report['metrics']['imported_sales'] == 3
    assert data['sales']['quantity'].sum() == 12
    assert data['sales']['source_row'].is_unique
    assert set(data['sales']['sku']) == {'00000123', '00000987'}
    assert data['sales']['customer_id'].eq('UNKNOWN').all()
    assert data['sales']['customer_id_unknown'].all()
    assert data['sales']['price_unknown'].all()
    assert data['sales']['price'].eq(0).all()
    assert data['suppliers']['cost_unknown'].all()
    assert data['suppliers']['unit_cost'].eq(0).all()
    assert data['sales'].loc[data['sales'].quantity < 0, 'transaction_type'].tolist() == ['return']
    assert data['stockouts'].empty
    assert report['metrics']['as_of'] == '2026-09-22'
    assert report['warnings']


@pytest.mark.parametrize('brand', ['Systeme', 'IEK'])
def test_partner_moq_and_supplier_article_do_not_replace_internal_sku(brand):
    data, report = parse_partner_archive(partner_zip(brand), f'{brand}.zip', 14)
    assert report['errors'] == []
    policies = data['suppliers'].set_index('sku')
    assert policies.loc['00000123', 'supplier_article'] == 'VENDOR-A'
    assert policies.loc['00000123', 'package_size'] == (12 if brand == 'Systeme' else 1)
    assert policies.loc['00000123', 'moq'] == (0 if brand == 'Systeme' else 24)
    assert policies.loc['00000987', 'package_size'] == (.25 if brand == 'Systeme' else 1)
    assert policies.loc['00000987', 'moq'] == (0 if brand == 'Systeme' else .5)
    assert policies['lead_time_days'].eq(14).all()
    assert policies['lead_time_source'].eq('user_confirmed').all()


def test_systeme_dated_free_stock_overrides_monthly_opening_only_for_existing_sku():
    data, report = parse_partner_archive(partner_zip(), 'Systeme.zip', 14)
    assert report['errors'] == []
    stock = data['stock'].set_index('sku')
    assert stock.loc['00000123', 'current_stock'] == 9
    assert stock.loc['00000123', 'balance_date'] == pd.Timestamp('2026-09-22')
    assert not bool(stock.loc['00000123', 'balance_is_stale'])
    assert stock.loc['00000987', 'current_stock'] == 30
    assert stock.loc['00000987', 'balance_date'] == pd.Timestamp('2026-09-01')
    assert bool(stock.loc['00000987', 'balance_is_stale'])
    assert stock.loc['00000987', 'source_warning']


def test_iek_monthly_opening_is_not_presented_as_current_stock():
    data, report = parse_partner_archive(partner_zip('IEK'), 'IEK.zip', 14)
    assert report['errors'] == []
    assert data['stock']['balance_is_stale'].all()
    assert data['stock']['balance_date'].eq(pd.Timestamp('2026-09-01')).all()
    assert data['stock']['as_of'].eq(pd.Timestamp('2026-09-22')).all()
    assert set(data['stock']['current_stock']) == {15, 30}


@pytest.mark.parametrize('brand', ['Systeme', 'IEK'])
def test_partner_known_eta_and_unknown_eta_are_preserved_separately(brand):
    data, report = parse_partner_archive(partner_zip(brand), f'{brand}.zip', 14)
    assert report['errors'] == []
    assert len(data['transit']) == 2
    known = data['transit'][~data['transit']['arrival_date_unknown']]
    unknown = data['transit'][data['transit']['arrival_date_unknown']]
    assert known.iloc[0]['expected_arrival_date'] == pd.Timestamp('2026-09-25')
    assert known.iloc[0]['quantity_in_transit'] == 7
    assert pd.isna(unknown.iloc[0]['expected_arrival_date'])
    assert unknown.iloc[0]['quantity_in_transit'] == 3
    assert report['metrics']['transit_quantity'] == 10


def test_partner_cutoff_excludes_later_sales_and_later_free_stock_snapshot():
    data, report = parse_partner_archive(partner_zip(), 'Systeme.zip', 14, '2026-09-20')
    assert report['errors'] == []
    assert len(data['sales']) == 1
    assert report['metrics']['future_sales_excluded'] == 2
    assert data['stock'].set_index('sku').loc['00000123', 'current_stock'] == 15
    assert data['stock']['balance_is_stale'].all()


def test_partner_historical_cutoff_does_not_use_a_future_inbound_snapshot():
    data, report = parse_partner_archive(partner_zip(), 'Systeme.zip', 14, '2026-09-20')
    assert report['errors'] == []
    assert data['transit'].empty
    assert report['warnings']


@pytest.mark.parametrize('kwargs,error_fragment', [
    ({'other_warehouse': True}, 'multiple sales warehouses'),
    ({'duplicate_sales_file': True}, 'More than one sales workbook'),
])
def test_ambiguous_partner_archive_is_rejected_instead_of_silently_double_counted(kwargs, error_fragment):
    data, report = parse_partner_archive(partner_zip(**kwargs), 'Systeme.zip', 14)
    assert any(error_fragment in error for error in report['errors'])
    assert data['sales'].empty


def test_partner_requires_valid_explicit_lead_time():
    data, report = parse_partner_archive(partner_zip(), 'Systeme.zip', 0)
    assert report['errors']
    assert data['sales'].empty


@pytest.mark.parametrize('brand', ['Systeme', 'IEK'])
def test_excel_na_optional_supplier_policy_keeps_sales_and_reports_unknown_constraint(brand):
    data, report = parse_partner_archive(partner_zip(brand, unknown_policy=True), f'{brand}.zip', 14)
    assert report['errors'] == []
    assert len(data['sales']) == 3
    assert any('#N/A' in warning or 'constraint' in warning.lower() or 'policy' in warning.lower() for warning in report['warnings'])
    policy = data['suppliers'].set_index('sku').loc['00000123']
    assert any(bool(policy.get(field, False)) for field in ('moq_unknown', 'package_unknown', 'constraint_unknown'))
