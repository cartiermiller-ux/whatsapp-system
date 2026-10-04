"""Atomic recharge credits from administrator review or signed payment-verifier callbacks."""
from datetime import datetime
from decimal import Decimal
import hashlib
import hmac
import json
import os
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
import main as m
import operations

router = APIRouter(prefix='/api/v1/balance')


class PaymentReceipt(m.TenantOwned, m.Base):
    __tablename__ = 'payment_receipt'
    id = m.Column(m.Integer, primary_key=True)
    tx_hash = m.Column(m.String(128), unique=True, index=True)
    order_id = m.Column(m.Integer, unique=True, index=True)
    amount = m.Column(m.Numeric(18, 6))
    source = m.Column(m.String(20))
    created_at = m.Column(m.DateTime, default=datetime.now)


class PaymentEvent(BaseModel):
    order_no: str = Field(min_length=1, max_length=64)
    tx_hash: str = Field(min_length=16, max_length=128)
    amount: Decimal = Field(gt=0)
    currency: str
    chain: str
    address: str
    confirmations: int = Field(ge=1)


def credit_order(order_id, db, *, tx_hash='', source='manual', user=None):
    order = db.get(m.RechargeOrder, order_id)
    if not order:
        raise HTTPException(404, '充值订单不存在')
    if source == 'manual':
        tx_hash = f'manual:{order.order_no}'
    receipt = db.query(PaymentReceipt).filter_by(tx_hash=tx_hash).first()
    if receipt:
        if receipt.order_id != order.id:
            raise HTTPException(409, '该交易已用于另一笔订单')
        return {'code': 0, 'data': {'order': m.order_dict(order), 'balance': m._money(m.current_balance(db)), 'duplicate': True}}
    if order.status != 'pending':
        raise HTTPException(409, f'订单状态为 {order.status}，无法确认到账')
    if order.expire_at and order.expire_at < datetime.now():
        raise HTTPException(409, '订单已过期，请人工核对到账情况')
    try:
        # Conditional update is the DB lock/claim, covering concurrent manual and webhook confirmations.
        claimed = db.query(m.RechargeOrder).filter_by(id=order.id, status='pending').update(
            {'status': 'paid', 'paid_at': datetime.now(), 'tx_hash': tx_hash}, synchronize_session=False)
        if claimed != 1:
            raise HTTPException(409, '订单已被其他请求处理')
        before = m.current_balance(db)
        db.add(PaymentReceipt(tx_hash=tx_hash, order_id=order.id, amount=order.amount, source=source))
        tx = m.BalanceTransaction(type='recharge', amount=order.amount, balance_before=before,
                                  balance_after=before+order.amount, currency=order.currency,
                                  result='success', remark=f'充值订单 {order.order_no} {"人工审核" if source=="manual" else "核验回调"}到账')
        db.add(tx)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '交易或订单已入账，禁止重复入账')
    db.refresh(order)
    if user:
        m.log_operation(db, 'confirm_recharge', target=order.order_no, detail=f'人工审核确认 {order.amount} {order.currency}', user=user)
    return {'code': 0, 'data': {'order': m.order_dict(order), 'transaction': m.transaction_dict(tx),
                              'balance': m._money(m.current_balance(db)), 'duplicate': False}}


@router.post('/payment-webhook')
async def payment_webhook(request: Request, x_payment_signature: str = Header(''), x_payment_timestamp: str = Header(''), db=Depends(m.get_db)):
    secret = os.environ.get('PAYMENT_WEBHOOK_SECRET', '')
    if not secret:
        raise HTTPException(503, '尚未配置到账核验回调')
    try:
        timestamp = int(x_payment_timestamp)
    except ValueError:
        raise HTTPException(401, '回调时间戳无效')
    if abs(time.time()-timestamp) > 300:
        raise HTTPException(401, '回调签名已过期')
    raw = await request.body()
    expected = hmac.new(secret.encode(), x_payment_timestamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_payment_signature):
        raise HTTPException(401, '回调签名无效')
    try:
        event = PaymentEvent.model_validate_json(raw)
    except ValueError:
        raise HTTPException(422, '到账回调字段无效')
    with operations._channel_lock:
        # A verified provider callback derives ownership from our order, never its payload.
        with m.system_session() as lookup:
            tenant_id = lookup.query(m.RechargeOrder.tenant_id).filter_by(order_no=event.order_no).scalar()
        if tenant_id is None:
            raise HTTPException(404, '充值订单不存在')
        m.bind_tenant(db, tenant_id)
        order = db.query(m.RechargeOrder).filter_by(order_no=event.order_no).first()
        if not order:
            raise HTTPException(404, '充值订单不存在')
        if event.amount != order.amount or event.currency != order.currency or event.chain != order.chain or event.address != order.address:
            raise HTTPException(422, '到账金额、币种、链或收款地址与订单不匹配')
        minimum = int(m.get_setting(db, 'payment_min_confirmations', 20))
        if event.confirmations < minimum:
            raise HTTPException(409, '链上确认数不足')
        return credit_order(order.id, db, tx_hash=event.tx_hash, source='webhook')
