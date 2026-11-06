"""Periodic, idempotent membership installment recovery."""
from .celery_app import celery_app

@celery_app.task(name='membership.credit_reconcile')
def reconcile():
    from .viral_insights_membership import reconcile_credit_grants
    return reconcile_credit_grants()
