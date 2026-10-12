"""initial schema: shops, categories, products, cart_items, orders, order_items

Revision ID: 0001
Revises: 
Create Date: 2026-09-26 14:02:12.574851

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('shops',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('admin_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('bot_token_encrypted', sa.Text(), nullable=False),
    sa.Column('bot_id', sa.BigInteger(), nullable=False),
    sa.Column('bot_username', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_shops')),
    sa.UniqueConstraint('bot_id', name=op.f('uq_shops_bot_id'))
    )
    op.create_index(op.f('ix_shops_owner_id'), 'shops', ['owner_id'], unique=False)
    op.create_table('categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], name=op.f('fk_categories_shop_id_shops'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('shop_id', 'name', name=op.f('uq_categories_shop_id_name'))
    )
    op.create_index(op.f('ix_categories_shop_id'), 'categories', ['shop_id'], unique=False)
    op.create_table('orders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('customer_name', sa.String(length=128), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('delivery_method', sa.Enum('pickup', 'delivery', name='delivery_method', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('comment', sa.Text(), server_default='', nullable=False),
    sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('status', sa.Enum('new', 'in_progress', 'done', 'cancelled', name='order_status', native_enum=False, create_constraint=True, length=32), server_default='new', nullable=False),
    sa.Column('payment_method', sa.Enum('manual', name='payment_method', native_enum=False, create_constraint=True, length=32), server_default='manual', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("delivery_method <> 'delivery' OR address IS NOT NULL", name=op.f('ck_orders_address_for_delivery')),
    sa.CheckConstraint('total >= 0', name=op.f('ck_orders_total_non_negative')),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], name=op.f('fk_orders_shop_id_shops'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders'))
    )
    op.create_index(op.f('ix_orders_shop_id'), 'orders', ['shop_id'], unique=False)
    op.create_index(op.f('ix_orders_user_id'), 'orders', ['user_id'], unique=False)
    op.create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('old_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('image_path', sa.String(length=255), nullable=True),
    sa.Column('in_stock', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('old_price IS NULL OR old_price >= 0', name=op.f('ck_products_old_price_non_negative')),
    sa.CheckConstraint('price >= 0', name=op.f('ck_products_price_non_negative')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_products_category_id_categories'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], name=op.f('fk_products_shop_id_shops'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products'))
    )
    op.create_index(op.f('ix_products_category_id'), 'products', ['category_id'], unique=False)
    op.create_index(op.f('ix_products_shop_id'), 'products', ['shop_id'], unique=False)
    op.create_table('cart_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_cart_items_quantity_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_cart_items_product_id_products'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], name=op.f('fk_cart_items_shop_id_shops'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cart_items')),
    sa.UniqueConstraint('shop_id', 'user_id', 'product_id', name=op.f('uq_cart_items_shop_id_user_id_product_id'))
    )
    op.create_table('order_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=True),
    sa.Column('product_name', sa.String(length=128), nullable=False),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.CheckConstraint('price >= 0', name=op.f('ck_order_items_price_non_negative')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_order_items_quantity_positive')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_items_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_order_items_product_id_products'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_items'))
    )
    op.create_index(op.f('ix_order_items_order_id'), 'order_items', ['order_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_order_items_order_id'), table_name='order_items')
    op.drop_table('order_items')
    op.drop_table('cart_items')
    op.drop_index(op.f('ix_products_shop_id'), table_name='products')
    op.drop_index(op.f('ix_products_category_id'), table_name='products')
    op.drop_table('products')
    op.drop_index(op.f('ix_orders_user_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_shop_id'), table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_categories_shop_id'), table_name='categories')
    op.drop_table('categories')
    op.drop_index(op.f('ix_shops_owner_id'), table_name='shops')
    op.drop_table('shops')
