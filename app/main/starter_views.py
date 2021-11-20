from app.main import main
from flask import g, url_for, render_template, request, redirect, session as http_session, abort, current_app, flash, jsonify
from flask_babel import lazy_gettext
from app.main.forms import *
from app.models import *
from app import db
from uuid import UUID, uuid4
from app.decorators import InSession
from app.services import SessionManager
from app.services.registrant_stats import RegistrantStats
from app.services.ksvotes_redis import KSVotesRedis
from app.services.early_voting_locations import EarlyVotingLocations
from app.services.dropboxes import Dropboxes
from app.services.steps import Step_0
from app.main.helpers import guess_locale
from sqlalchemy import func
import sys
import datetime
import json

import tracemalloc
tracemalloc.start(10)

@main.route('/terms', methods=['GET'])
def terms():
    g.locale = guess_locale()
    return render_template('terms.html')


@main.route('/privacy-policy', methods=['GET'])
def privacy():
    g.locale = guess_locale()
    return render_template('privacy-policy.html')


@main.route('/about', methods=['GET'])
def about_us():
    g.locale = guess_locale()
    return render_template('about.html')


# step 0 / 0x
@main.route('/', methods=["GET", "POST"])
@InSession
def index():
    registrant = g.registrant
    form = FormStep0()
    if http_session.get('ref'):
        form = FormStep0(ref=http_session.get('ref'))
        print("http sess")
    elif request.cookies.get('ref'):
        print("cookies")
        form = FormStep0(ref=request.cookies.get('ref'))
    if registrant:
        print("registrant")
        print("ref")
        form = FormStep0(
            ref=http_session.get('ref'),
            state=registrant.try_value('state'),
            city=registrant.try_value('city'),
            street=registrant.try_value('street'),
            name_first=registrant.try_value('name_first'),
            name_last=registrant.try_value('name_last'),
            dob=registrant.try_value('dob'),
            zip=registrant.try_value('zip'),
            email=registrant.try_value('email'),
            phone=registrant.try_value('phone')
        )

    if request.method == "POST" and form.validate_on_submit():
        print("form.data:")
        print(form.data)
        step = Step_0(form.data)
        if registrant:
            registrant.update(form.data)
        else:
            sid = UUID(http_session.get('session_id'), version=4)
            zipcode = form.data.get('zip')
            registrant = Registrant(
                county=ZIPCode.guess_county(zipcode),
                ref=form.data.get('ref'),
                registration_value=form.data,
                session_id=sid,
                lang=g.lang_code,
            )
            registrant.set_value('zip', zipcode)
            db.session.add(registrant)

        skip_sos = request.values.get('skip-sos')
        step.run(skip_sos)
        registrant.reg_lookup_complete = step.reg_lookup_complete
        registrant.reg_found = True if step.reg_found else False
        registrant.dob_year = registrant.get_dob_year()
        sos_reg = None
        sos_failure = None
        if step.reg_found:
            sos_reg = []
            print(step.reg_found)
            for rec in step.reg_found:

                rec2save = {'tree': rec['tree']}
                if 'sample_ballots' in rec:
                    rec2save['sample_ballot'] = rec['sample_ballots']
                if 'districts' in rec:
                    rec2save['districts'] = rec['districts']
                if 'elections' in rec:
                    rec2save['elections'] = rec['elections']
                if 'polling' in rec:
                    rec2save['polling'] = rec['polling']

                # prepopulate address and party, if possible
                try:
                    registrant.populate_address(rec2save['tree'])
                except:
                    # just swallow errors for now
                    err = sys.exc_info()[0]
                    current_app.logger.error(str(err))

                sos_reg.append(rec2save)
        else:
            sos_failure = step.voter_view_fail

        registrant.update({'sos_reg': sos_reg, 'skip_sos': skip_sos, 'sos_failure': sos_failure})
        registrant.save(db.session)

        # small optimization for common case.
        if skip_sos and not current_app.config['ENABLE_AB']:
            return redirect(url_for('main.vr1_citizenship'))

        session_manager = SessionManager(registrant, step)
        return redirect(session_manager.get_redirect_url())

    else:
        has_announcements = False
        if lazy_gettext('announce') != "announce":
            has_announcements = True
        return render_template('index.html', form=form, has_announcements=has_announcements)


@main.route('/change-or-apply/', methods=["GET"])
@InSession
def change_or_apply():
    reg = g.registrant
    sos_reg = reg.try_value('sos_reg')
    skip_sos = reg.try_value('skip_sos')
    sos_failure = reg.try_value('sos_failure')
    county = reg.county
    if not county and sos_reg:
      county = sos_reg[0]['tree']['County']
    clerk = None
    evl = None
    dropboxes = None
    if county:
        clerk = Clerk.find_by_county(county)
        evl = EarlyVotingLocations(county).locations
        dropboxes = Dropboxes(county).dropboxes

    return render_template(
        'change-or-apply.html',
        skip_sos=skip_sos,
        sos_reg=sos_reg,
        sos_failure=sos_failure,
        clerk=clerk,
        early_voting_locations=evl,
        dropboxes=dropboxes
    )


@main.route('/change-county', methods=['POST'])
@InSession
def change_county():
    reg = g.registrant
    existing_county = reg.county
    new_county = request.values.get('county')
    redirect_url = request.values.get('return')

    if not redirect_url:
        redirect_url = url_for('main.index')

    if not new_county or new_county == existing_county:
        current_app.logger.error('unable to change county')
        redirect(redirect_url)

    current_app.logger.debug('new county %s return to %s' % (new_county, redirect_url))
    reg.county = new_county

    # must invalidate any cached images since county is on the forms
    if reg.try_value('ab_forms'):
        reg.sign_ab_forms()
        flash(lazy_gettext('ab_forms_county_changed'), 'info')

    reg.save(db.session)

    return redirect(redirect_url)


@main.route('/forget', methods=['GET', 'POST'])
def forget_session():
    g.locale = guess_locale()
    http_session['session_id'] = None
    # flash(lazy_gettext('session_forgotten'), 'info') # TODO wordsmith this
    return redirect(url_for('main.index'))


@main.route('/county/<county>', methods=['GET'])
def clerk_details(county):
    g.locale = guess_locale()
    clerk = Clerk.find_by_county(county)
    if clerk:
        evl = EarlyVotingLocations(county)
        d = Dropboxes(county)
        return render_template('county.html', clerk=clerk, early_voting_locations=evl.locations, dropboxes=d.dropboxes)
    else:
        return abort(404)


# easy to remember
@main.route('/demo', methods=['GET'], strict_slashes=False)
def demo_mode():
    return redirect(url_for('main.referring_org', ref='demo'))


@main.route('/r/<refcode>', methods=['GET'], strict_slashes=False)
def make_davis_happy_redirect(refcode):
    return redirect(url_for('main.referring_org', ref=refcode))


@main.route('/registration', methods=['GET'], strict_slashes=False)
def old_reg_link():
    return redirect(url_for('main.referring_org', ref='old-reg'))


@main.route('/ref', methods=['GET', 'POST'], strict_slashes=False)
def referring_org():
    # we will accept whatever subset of step0 fields are provided.
    # we always start a new session, but we require a 'ref' code.
    if not request.values.get('ref'):
        return abort(404)

    sid = str(uuid4())

    # special 'ref' value of 'demo' attaches to the DEMO_UUID if defined
    if request.values['ref'] == 'demo' and current_app.config['DEMO_UUID']:
        sid = current_app.config['DEMO_UUID']

    http_session['session_id'] = sid

    # if this is a GET request, make ref sticky via a cookie
    # and immediately redirect
    if request.method == 'GET':
        http_session['ref'] = request.values['ref']
        response = current_app.make_response(redirect(url_for('main.index')))
        response.set_cookie('ref', value=request.values['ref'])
        return response

    registration = {
        'state': request.values.get('state', ''),
        'city': request.values.get('city', ''),
        'street': request.values.get('street', ''),
        'name_last': request.values.get('name_last', ''),
        'name_first': request.values.get('name_first', ''),
        'dob': request.values.get('dob', ''),
        'email': request.values.get('email', ''),
        'phone': request.values.get('phone', ''),
        'zip': request.values.get('zip', ''),
    }
    registrant = Registrant(
        session_id=sid,
        ref=request.values['ref'],
        registration_value=registration
    )
    db.session.add(registrant)
    db.session.commit()
    return redirect(url_for('main.index'))


@main.route('/api/total-processed/', methods=['GET'])
def api_total_processed():
    s = RegistrantStats()
    r = KSVotesRedis()
    def get_vr_total():
        return s.vr_total_processed()

    def get_ab_total():
        return s.ab_total_processed()

    # cache for 1 hour
    ttl = 60 * 60
    reg_count = int(r.get_or_set('vr-total-processed', get_vr_total, ttl))
    ab_count = int(r.get_or_set('ab-total-processed', get_ab_total, ttl))

    return jsonify(registrations=reg_count, advanced_ballots=ab_count)


@main.route('/stats/', methods=['GET'])
def stats():
    g.locale = guess_locale()
    ninety_days = datetime.timedelta(days=90)
    today = datetime.date.today()
    s = RegistrantStats()
    vr_stats = s.vr_through_today(today - ninety_days)
    ab_stats = s.ab_through_today(today - ninety_days)

    stats = {'vr': [], 'ab': []}
    for r in vr_stats:
      stats['vr'].append(r.values())
    for r in ab_stats:
      stats['ab'].append(r.values())

    return render_template('stats.html', stats=stats)

@main.route('/memory/', methods=['GET'])
def memory():
    import tracemalloc
    import linecache
    import os
    key_type = 'lineno'
    limit = 20
    snapshot = tracemalloc.take_snapshot()
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    top_stats = snapshot.statistics(key_type)

    buff = []

    buff.append("Top %s lines" % limit)
    for index, stat in enumerate(top_stats[:limit], 1):
        frame = stat.traceback[0]
        buff.append("#%s: %s:%s: %.1f KiB"
              % (index, frame.filename, frame.lineno, stat.size / 1024))
        line = linecache.getline(frame.filename, frame.lineno).strip()
        if line:
            buff.append('    %s' % line)

    other = top_stats[limit:]
    if other:
        size = sum(stat.size for stat in other)
        buff.append("%s other: %.1f KiB" % (len(other), size / 1024))
    total = sum(stat.size for stat in top_stats)
    buff.append("Total allocated size: %.1f KiB" % (total / 1024))

    return jsonify(status='ok', total=total, report=buff, pid=os.getpid())


# testing backend api for checking voter registration status
@main.route('/test/', methods=["POST"])
def test():
    
    someJson = request.form
    """
    form = FormStep0(
        ref=request.form.get('ref'),
        state=request.form.get('state'),
        city=request.form.get('city'),
        street=request.form.get('street'),
        name_first=request.form.get('name_first'),
        name_last=request.form.get('name_last'),
        dob=request.form.get('dob'),
        zip=request.form.get('zip'),
        email=request.form.get('email'),
        phone=request.form.get('phone')
    )
    """
    step = Step_0(someJson)
    regFound = step.lookup_registration(
        state=request.form.get('state'),
        city=request.form.get('city'),
        street=request.form.get('street'),
        name_first=request.form.get('name_first'),
        name_last=request.form.get('name_last'),
        dob=request.form.get('dob'),
        zipcode=request.form.get('zip')
    )
    #print("regFound: ")
    #print(regFound)
    
    if (regFound and 'status' not in regFound) or (regFound and 'status' in regFound and regFound['status'] == 'active'):
        return jsonify({ 'registered': True})
        '''
        sos_reg = []
        for rec in regFound:
            rec2save = {'tree': rec['tree']}
            if 'sample_ballots' in rec:
                rec2save['sample_ballot'] = rec['sample_ballots']
            if 'districts' in rec:
                rec2save['districts'] = rec['districts']
            if 'elections' in rec:
                rec2save['elections'] = rec['elections']
            if 'polling' in rec:
                rec2save['polling'] = rec['polling']
            sos_reg.append(rec2save)
        print("sos_reg: ")
        print(sos_reg)
        '''
    else:
        return { 'registered': False }