def pre_init_hook(cr):
    """
    The objective of this hook is to speed up the installation
    of the module on an existing Odoo instance.

    Without this script, big databases can take a long time to install this
    module.
    """
    # Check if the column already exists before adding it
    cr.execute(
        """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='mail_message' AND column_name='gateway_channel_id'
    """
    )
    if not cr.fetchone():
        cr.execute(
            """
            ALTER TABLE mail_message
            ADD COLUMN gateway_channel_id int
        """
        )
