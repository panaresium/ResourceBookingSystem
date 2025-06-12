import click
from flask.cli import with_appcontext
from datetime import timedelta, timezone # timezone might not be used directly here, but good for clarity
from extensions import db
from models import Booking, BookingSettings

@click.command('migrate_booking_times_to_local')
@with_appcontext
def migrate_booking_times_to_local_command():
    """Converts existing Booking times from naive UTC to naive venue local time."""
    click.echo('Starting booking time migration...')

    booking_settings = BookingSettings.query.first()
    if not booking_settings:
        click.echo(click.style('Error: BookingSettings not found. Cannot determine global_time_offset_hours.', fg='red'))
        return

    # Ensure global_time_offset_hours is treated as 0 if None, though it has a server_default='0'
    global_time_offset_hours = booking_settings.global_time_offset_hours if booking_settings.global_time_offset_hours is not None else 0
    click.echo(f'Using global_time_offset_hours: {global_time_offset_hours}')

    bookings_to_migrate = Booking.query.all()
    if not bookings_to_migrate:
        click.echo('No bookings found to migrate.')
        return

    migrated_count = 0
    error_count = 0

    for booking in bookings_to_migrate:
        try:
            updated = False
            # These fields were previously stored as naive UTC.
            # We convert them to naive venue local time.
            # new_local_time = old_naive_utc_time + offset
            # (If offset is +7 for UTC+7 venue, 01:00 UTC becomes 08:00 local)

            if booking.start_time:
                # Assuming booking.start_time is naive UTC
                booking.start_time = booking.start_time + timedelta(hours=global_time_offset_hours)
                updated = True

            if booking.end_time:
                # Assuming booking.end_time is naive UTC
                booking.end_time = booking.end_time + timedelta(hours=global_time_offset_hours)
                updated = True

            if booking.checked_in_at:
                # Assuming booking.checked_in_at was naive UTC
                # This field is now intended to store naive *local* "now" at the time of check-in.
                # So, if it was naive UTC, it should be converted to naive local.
                booking.checked_in_at = booking.checked_in_at + timedelta(hours=global_time_offset_hours)
                updated = True

            if booking.checked_out_at:
                # Assuming booking.checked_out_at was naive UTC
                # This field is now intended to store naive *local* "now" at the time of check-out.
                booking.checked_out_at = booking.checked_out_at + timedelta(hours=global_time_offset_hours)
                updated = True

            # booking_display_start_time and booking_display_end_time are already Time objects representing local time of day.
            # last_modified is an onupdate=datetime.utcnow, so it should remain UTC.
            # check_in_token_expires_at: This is naive UTC and should remain so.

            if updated:
                migrated_count += 1
                if migrated_count > 0 and migrated_count % 100 == 0: # Ensure commit happens after some changes
                    click.echo(f'Migrated {migrated_count} bookings...')
                    db.session.commit() # Commit in batches

        except Exception as e:
            error_count += 1
            click.echo(click.style(f'Error migrating booking ID {booking.id}: {str(e)}', fg='red'))
            db.session.rollback() # Rollback current change on error

    try:
        db.session.commit() # Commit any remaining changes
    except Exception as e_final_commit:
        error_count +=1 # Consider any uncommitted changes as errors or handle more granularly
        click.echo(click.style(f'Error during final commit: {str(e_final_commit)}', fg='red'))
        db.session.rollback()

    click.echo(click.style(f'Migration complete. Successfully migrated {migrated_count} bookings.', fg='green'))
    if error_count > 0:
        click.echo(click.style(f'{error_count} errors occurred.', fg='red'))

def register_cli_commands(app):
    app.cli.add_command(migrate_booking_times_to_local_command)
