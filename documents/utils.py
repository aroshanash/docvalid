import requests
from decimal import Decimal
from .models import CurrencyRate

EXCHANGE_API = "https://api.exchangerate.host/latest"

def get_rate_to_aed(currency: str) -> Decimal:
    currency = currency.upper()
    try:
        cr = CurrencyRate.objects.get(currency=currency)
        return Decimal(cr.rate_to_aed)
    except CurrencyRate.DoesNotExist:
        pass

    params = {'base': currency, 'symbols': 'AED'}
    resp = requests.get(EXCHANGE_API, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get('rates') and 'AED' in data['rates']:
        rate = Decimal(str(data['rates']['AED']))
        CurrencyRate.objects.update_or_create(currency=currency, defaults={'rate_to_aed': rate})
        return rate
    raise ValueError(f"Unable to fetch rate for {currency}")

def calculate_duties_from_hs(hs_code: str, value_in_aed: Decimal):
    if hs_code and str(hs_code).strip().startswith('85'):
        pct = Decimal('0.05')
    else:
        pct = Decimal('0.10')
    duties = (value_in_aed * pct).quantize(Decimal('0.01'))
    return {'duty_percentage': pct, 'duties': duties}