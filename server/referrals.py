"""Invitation attribution. Registration and task completion never award points."""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, Index, MetaData, String, Table, Text, inspect, text
from . import accounts, database

metadata=MetaData()
referral_table=Table('referrals',metadata,
    Column('id',String(64),primary_key=True),Column('inviter_id',String(64),nullable=False),
    Column('invitee_id',String(64),nullable=False,unique=True),Column('code',String(16),nullable=False),
    Column('status',String(16),nullable=False,server_default='pending'),Column('signup_ip',String(64)),
    Column('reject_reason',String(64)),Column('created_at',Text,nullable=False),
    Column('activated_at',Text),Column('rewarded_at',Text))
Index('idx_referrals_inviter_time',referral_table.c.inviter_id,referral_table.c.created_at)
Index('idx_referrals_signup_ip',referral_table.c.signup_ip,referral_table.c.inviter_id,referral_table.c.created_at)
risk_table=Table('referral_reward_risks',metadata,
    Column('invitee_id',String(64),primary_key=True),Column('reason',Text,nullable=False),
    Column('status',String(16),nullable=False),Column('updated_at',Text,nullable=False))
CODE_ALPHABET='23456789ABCDEFGHJKMNPQRSTUVWXYZ'
CODE_LENGTH=6


def init_schema():
    metadata.create_all(database.ENGINE)
    cols={c['name'] for c in inspect(database.ENGINE).get_columns('users')}
    with database.ENGINE.begin() as c:
        if 'invite_code' not in cols:c.execute(text('ALTER TABLE users ADD COLUMN invite_code VARCHAR(16)'))
        c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_users_invite_code ON users(invite_code)'))
    # Preserve historical rows, including orphans requiring manual review.


def _normalize(code):
    return ''.join(c for c in str(code or '').strip().upper() if c.isalnum())[:32]


def ensure_code(user_id):
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        lock=' FOR UPDATE' if database.ENGINE.dialect.name=='postgresql' else ''
        row=c.execute('SELECT invite_code FROM users WHERE id=?'+lock,(user_id,)).fetchone()
        if not row:raise ValueError('用户不存在')
        if row['invite_code']:c.execute('COMMIT');return row['invite_code']
        for _ in range(32):
            code=''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if c.execute('SELECT 1 FROM users WHERE invite_code=?',(code,)).fetchone():continue
            c.execute('UPDATE users SET invite_code=? WHERE id=?',(code,user_id))
            c.execute('COMMIT');return code
        raise RuntimeError('邀请码生成失败')


def bind_signup(invitee_id,code,ip):
    code=_normalize(code)
    if not code:return {'status':'none'}
    try:
        with accounts._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            lock=' FOR UPDATE' if database.ENGINE.dialect.name=='postgresql' else ''
            c.execute('SELECT id FROM users WHERE id=?'+lock,(invitee_id,)).fetchone()
            inviter=c.execute('SELECT id,status FROM users WHERE invite_code=?',(code,)).fetchone()
            if not inviter or inviter['status']!='active':c.execute('ROLLBACK');return {'status':'ignored','reason':'code_not_found'}
            if inviter['id']==invitee_id:c.execute('ROLLBACK');return {'status':'ignored','reason':'self_referral'}
            if c.execute('SELECT 1 FROM referrals WHERE invitee_id=?',(invitee_id,)).fetchone():
                c.execute('ROLLBACK');return {'status':'ignored','reason':'already_referred'}
            now=accounts.utc_now()
            recent=c.execute('SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND created_at>=?',
                (inviter['id'],(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())).fetchone()[0]
            monthly=c.execute('SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND created_at>=?',
                (inviter['id'],(datetime.now(timezone.utc)-timedelta(days=30)).isoformat())).fetchone()[0]
            c.execute("INSERT INTO referrals(id,inviter_id,invitee_id,code,status,signup_ip,created_at) VALUES(?,?,?,?,'pending',?,?)",
                (secrets.token_hex(16),inviter['id'],invitee_id,code,ip,now))
            # Binding is never discarded for volume or shared IP. Only award review.
            if recent>=5 or monthly>=20:
                c.execute("INSERT OR IGNORE INTO referral_reward_risks(invitee_id,reason,status,updated_at) VALUES(?,'短时间集中邀请，待审核','review',?)",(invitee_id,now))
            c.execute('COMMIT')
            return {'status':'bound','bonus':0}
    except Exception:
        logging.getLogger(__name__).exception('referral.bind_failed invitee=%s',invitee_id)
        return {'status':'ignored','reason':'internal_error'}


def on_usage_completed(request_id):
    """Retired compatibility entry; grants nothing, even for legacy callers."""
    return None


def _masked(value):
    return str(value or '好友')[:1]+'***'


def summary(user_id):
    from . import referral_recharge as rr
    code=ensure_code(user_id)
    with accounts._connect() as c:
        cfg=c.execute('SELECT * FROM referral_campaign WHERE id=1').fetchone()
        rules=rr.json.loads(cfg['rules_json']) if cfg else rr.asdict(rr.Rules())
        rows=c.execute('''SELECT r.invitee_id,r.created_at,u.display_name,
            (SELECT COUNT(*) FROM alipay_recharges a JOIN alipay_orders o ON o.out_trade_no=a.out_trade_no
             WHERE a.user_id=r.invitee_id AND a.status='CREDITED' AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED')) paid,
            (SELECT COALESCE(SUM(granted-reversed-debt),0) FROM referral_recharge_rewards w WHERE w.invitee_id=r.invitee_id) earned
            FROM referrals r JOIN users u ON u.id=r.invitee_id WHERE r.inviter_id=? ORDER BY r.created_at DESC''',(user_id,)).fetchall()
        recent=c.execute('SELECT kind,granted,reversed,debt,status,created_at FROM referral_recharge_rewards WHERE inviter_id=? ORDER BY created_at DESC LIMIT 30',(user_id,)).fetchall()
        debt=c.execute('SELECT COALESCE(SUM(debt),0) FROM referral_recharge_rewards WHERE inviter_id=?',(user_id,)).fetchone()[0]
        pending=c.execute("SELECT COUNT(*) FROM referral_recharge_reviews WHERE inviter_id=? AND status='pending'",(user_id,)).fetchone()[0]
    return {'code':code,'path':'/?ref='+code,'enabled':bool(cfg and cfg['enabled']),
        'effective_at':cfg['effective_at'] if cfg else None,'rules':rules,
        'counts':{'total':len(rows),'paid':sum(bool(r['paid']) for r in rows)},
        'earned_points':sum(r['earned'] for r in rows),'debt_points':debt,'pending_count':pending,
        'invitees':[{'display_name':_masked(r['display_name']),'created_at':r['created_at'],
                     'paid':bool(r['paid']),'earned_points':r['earned']} for r in rows],
        'recent_rewards':[dict(r) for r in recent]}


def admin_summary():
    from . import referral_recharge
    return referral_recharge.admin_report()
