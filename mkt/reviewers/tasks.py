from django.conf import settings

from celeryutils import task
from tower import ugettext as _

import amo
from addons.tasks import create_persona_preview_images
from amo.decorators import write
from amo.storage_utils import move_stored_file
from amo.utils import LocalFileStorage, send_mail_jinja
from editors.models import ReviewerScore

import mkt.constants.reviewers as rvw


@task
def send_mail(cleaned_data, theme_lock):
    """
    Send emails out for respective review actions taken on themes.
    """
    theme = cleaned_data['theme']
    action = cleaned_data['action']
    comment = cleaned_data['comment']
    reject_reason = cleaned_data['reject_reason']

    reason = None
    if reject_reason:
        reason = rvw.THEME_REJECT_REASONS[reject_reason]
    elif action == rvw.ACTION_DUPLICATE:
        reason = _('Duplicate Submission')

    emails = set(theme.addon.authors.values_list('email', flat=True))
    context = {
        'theme': theme,
        'base_url': settings.SITE_URL,
        'reason': reason,
        'comment': comment
    }

    subject = None
    if action == rvw.ACTION_APPROVE:
        subject = _('Thanks for submitting your Theme')
        template = 'reviewers/themes/emails/approve.html'

    elif action == rvw.ACTION_REJECT:
        subject = _('A problem with your Theme submission')
        template = 'reviewers/themes/emails/reject.html'

    elif action == rvw.ACTION_DUPLICATE:
        subject = _('A problem with your Theme submission')
        template = 'reviewers/themes/emails/reject.html'

    elif action == rvw.ACTION_FLAG:
        subject = _('Theme submission flagged for review')
        template = 'reviewers/themes/emails/flag_reviewer.html'

        # Send the flagged email to themes email.
        emails = [settings.THEMES_EMAIL]

    elif action == rvw.ACTION_MOREINFO:
        subject = _('A question about your Theme submission')
        template = 'reviewers/themes/emails/moreinfo.html'
        context['reviewer_email'] = theme_lock.reviewer.email

    send_mail_jinja(subject, template, context,
                    recipient_list=emails, from_email=settings.ADDONS_EMAIL,
                    headers={'Reply-To': settings.THEMES_EMAIL})


@task
def approve_rereview(theme):
    """Replace original theme with pending theme on filesystem."""
    # If reuploaded theme, replace old theme design.
    storage = LocalFileStorage()
    rereview = theme.rereviewqueuetheme_set.all()
    reupload = rereview[0]

    if reupload.header_path != reupload.theme.header_path:
        create_persona_preview_images(
            src=reupload.header_path,
            full_dst=[
                reupload.theme.thumb_path,
                reupload.theme.icon_path],
            set_modified_on=[reupload.theme.addon])

        move_stored_file(
            reupload.header_path, reupload.theme.header_path,
            storage=storage)
    if reupload.footer_path != reupload.theme.footer_path:
        move_stored_file(
            reupload.footer_path, reupload.theme.footer_path,
            storage=storage)
    rereview.delete()

    theme.addon.increment_version()


@task
def reject_rereview(theme):
    """Delete pending theme from filesystem."""
    storage = LocalFileStorage()
    rereview = theme.rereviewqueuetheme_set.all()
    reupload = rereview[0]

    storage.delete(reupload.header_path)
    storage.delete(reupload.footer_path)
    rereview.delete()


@task
@write
def _batch_award_points(activity_logs, **kwargs):
    """For migration award_theme_rev_points."""
    for log in activity_logs:
        if not ReviewerScore.objects.filter(
            user=log.user, addon=log.arguments[0],
            score=amo.REVIEWED_SCORES.get(amo.REVIEWED_PERSONA),
            note_key=amo.REVIEWED_PERSONA, note='RETROACTIVE').exists():

            ReviewerScore.objects.create(
                user=log.user, addon=log.arguments[0],
                score=amo.REVIEWED_SCORES.get(amo.REVIEWED_PERSONA),
                note_key=amo.REVIEWED_PERSONA, note='RETROACTIVE')
