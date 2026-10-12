"""multi images, extra admins, buyer username

Этап 6.5: до 10 фото у товара (product_images), дополнительные админы (shop_admins,
admin_invites), username покупателя в заказе (orders.tg_username / tg_name).
Существующие фото переносятся из products.image_path ДО удаления колонки.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03 01:09:23.813096

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('admin_invites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('used_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], name=op.f('fk_admin_invites_shop_id_shops'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_invites')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_admin_invites_token_hash'))
    )
    op.create_index(op.f('ix_admin_invites_shop_id'), 'admin_invites', ['shop_id'], unique=False)
    op.create_table('shop_admins',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=True),
    sa.Column('username', sa.String(length=32), nullable=True),
    sa.Column('added_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], name=op.f('fk_shop_admins_shop_id_shops'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_shop_admins')),
    sa.UniqueConstraint('shop_id', 'user_id', name=op.f('uq_shop_admins_shop_id_user_id'))
    )
    op.create_index(op.f('ix_shop_admins_shop_id'), 'shop_admins', ['shop_id'], unique=False)
    op.create_table('product_images',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('path', sa.String(length=255), nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_product_images_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_product_images'))
    )
    op.create_index(op.f('ix_product_images_product_id'), 'product_images', ['product_id'], unique=False)
    op.add_column('orders', sa.Column('tg_username', sa.String(length=32), nullable=True))
    op.add_column('orders', sa.Column('tg_name', sa.String(length=128), nullable=True))
    # Перенос данных: каждое существующее фото становится первым (обложкой) в новой таблице
    op.execute(
        "INSERT INTO product_images (product_id, path, position) "
        "SELECT id, image_path, 0 FROM products WHERE image_path IS NOT NULL"
    )
    op.drop_column('products', 'image_path')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('products', sa.Column('image_path', sa.VARCHAR(length=255), autoincrement=False, nullable=True))
    # Откат: в старую схему помещается одно фото — возвращаем обложку (остальные теряются)
    op.execute(
        "UPDATE products p SET image_path = ("
        "  SELECT path FROM product_images i WHERE i.product_id = p.id ORDER BY position, id LIMIT 1)"
    )
    op.drop_column('orders', 'tg_name')
    op.drop_column('orders', 'tg_username')
    op.drop_index(op.f('ix_product_images_product_id'), table_name='product_images')
    op.drop_table('product_images')
    op.drop_index(op.f('ix_shop_admins_shop_id'), table_name='shop_admins')
    op.drop_table('shop_admins')
    op.drop_index(op.f('ix_admin_invites_shop_id'), table_name='admin_invites')
    op.drop_table('admin_invites')
