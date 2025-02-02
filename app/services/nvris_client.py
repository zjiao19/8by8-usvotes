from flask import g, current_app
from app.main.VR.example_form import signature_img_string
import os
import json
import newrelic.agent
from app.services.form_filler_service import FormFillerService

# Can be used to get the federal form as an image to display
class NVRISClient():

    def __init__(self, registrant):
        self.registrant = registrant
        self.lang = g.get('lang_code', current_app.config['BABEL_DEFAULT_LOCALE'])
        if self.lang == None:
            self.lang = registrant.lang or 'en' 
        self.nvris_url = os.getenv('NVRIS_URL')
        self.attempts = 0
        self.MAX_ATTEMPTS = 2

    def get_vr_form(self):
        if self.nvris_url == 'TESTING': # magic URL for testing mode
            return signature_img_string

        url = '/vr/' + self.lang
        current_app.logger.info("%s FormFiller request to %s" %(self.registrant.session_id, url))
        payload = self.marshall_payload('vr')

        print("payload: %s" %(payload)) # debug only -- no PII in logs
        return self.fetch_nvris_img(url, payload)

    def get_ab_form(self, election):
        if self.nvris_url == 'TESTING': # magic URL for testing mode
            return signature_img_string

        if election == 'permanent':
            flavor = 'ksav2'
        else:
            flavor = 'ksav1'
    
        url = '/av/' + flavor + '/' + self.lang

        current_app.logger.info("%s FormFiller request to %s" %(self.registrant.session_id, url))
        payload = self.marshall_payload(flavor, election=election)

        #print("payload: %s" %(payload)) # debug only -- no PII in logs
        return self.fetch_nvris_img(url, payload)

    def fetch_nvris_img(self, url, payload):
        if self.attempts > self.MAX_ATTEMPTS:
            return None

        payload['uuid'] = str(self.registrant.session_id)

        filler_service = FormFillerService(payload=payload, form_name=url)

        return filler_service.as_image()

    def marshall_payload(self, flavor, **kwargs):
        if flavor == 'vr':
            payload = self.marshall_vr_payload()
        elif flavor == 'ksav1':
            payload = self.marshall_ksav1_payload(**kwargs)
        elif flavor == 'ksav2':
            payload = self.marshall_ksav2_payload()
        else:
            raise Exception("unknown payload flavor %s" %(flavor))

        # remove the signature from payload if null because NVRIS will balk
        if not payload['signature']:
            payload.pop('signature')

        return payload

    def parse_election_date(self, election):
        import re
        pattern = '(Prim\w+|General) \((.+)\)'
        m = re.match(pattern, election)
        if m:
            return m.group(2)
        else:
            current_app.logger.error("%s No match for election '%s'" %(self.registrant.session_id, election))
            return '(none)'

    def normalize_unit(self, unit):
        import re
        return re.sub(r"^(#|apt.? |apartment )", '', unit, flags=re.IGNORECASE)

    def format_street_address(self, addr, unit):
        r = self.registrant
        street = r.try_value(addr)
        aptlot = self.normalize_unit(r.try_value(unit))
        if not aptlot or len(aptlot) == 0:
            return street
        else:
            return "{street} #{aptlot}".format(street=street, aptlot=aptlot)


    def marshall_ksav1_payload(self, **kwargs):
        election = kwargs['election']
        r = self.registrant
        sig = r.try_value('signature_string', None)
        return {
            'state': 'Kansas', # TODO r.try_value('state'),
            'county_2': r.county, # TODO corresponds with 'state'
            'county_1': r.county, # TODO different?
            'id_number': r.try_value('ab_identification'),
            'last_name': r.try_value('name_last'),
            'first_name': r.try_value('name_first'),
            'middle_initial': r.middle_initial(),
            'dob': r.try_value('dob'),
            'residential_address': self.format_street_address('addr', 'unit'),
            'residential_city': r.try_value('city'),
            'residential_state': r.try_value('state'),
            'residential_zip': r.try_value('zip'),
            'mailing_address': self.format_street_address('mail_addr', 'mail_unit'),
            'mailing_city': r.try_value('mail_city'),
            'mailing_state': r.try_value('mail_state'),
            'mailing_zip': r.try_value('mail_zip'),
            'election_date': self.parse_election_date(election),
            'signature': sig,
            'signature_date': r.signed_at_central_tz().strftime('%m/%d/%Y') if sig else False,
            'phone_number': r.try_value('phone'),
            'democratic': True if r.party.lower() == 'democratic' else False,
            'republican': True if r.party.lower() == 'republican' else False,
        }

    def marshall_ksav2_payload(self, **kwargs):
        r = self.registrant
        sig = r.try_value('signature_string', None)
        return {
            'state': 'Kansas', # TODO r.try_value('state'),
            'county_2': r.county, # TODO corresponds with 'state'
            'county_1': r.county, # TODO different?
            'id_number': r.try_value('ab_identification'),
            'last_name': r.try_value('name_last'),
            'first_name': r.try_value('name_first'),
            'middle_initial': r.middle_initial(),
            'dob': r.try_value('dob'),
            'residential_address': self.format_street_address('addr', 'unit'),
            'residential_city': r.try_value('city'),
            'residential_state': r.try_value('state'),
            'residential_zip': r.try_value('zip'),
            'mailing_address': self.format_street_address('mail_addr', 'mail_unit'),
            'mailing_state': r.try_value('mail_state'),
            'mailing_zip': r.try_value('mail_zip'),
            'reason_for_perm': r.try_value('perm_reason'),
            'signature': sig,
            'signature_date': r.signed_at_central_tz().strftime('%m/%d/%Y') if sig else False,
            'phone_number': r.try_value('phone'),
            'democratic': True if r.party.lower() == 'democratic' else False,
            'republican': True if r.party.lower() == 'republican' else False,
        }

    def marshall_vr_payload(self):
        r = self.registrant
        sig = r.try_value('signature_string', None)
        return {
            "00_citizen_yes": True if r.is_citizen else False,
            "00_citizen_no": False if r.is_citizen else True,
            "00_eighteenPlus_yes": True if r.is_eighteen else False,
            #"00_eighteenPlus_no": False if r.is_eighteen else True,
            "01_prefix_mr": True if r.try_value('prefix') == 'mr' else False,
            "01_prefix_mrs": True if r.try_value('prefix') == 'mrs' else False,
            "01_prefix_miss": True if r.try_value('prefix') == 'miss' else False,
            "01_prefix_ms": True if r.try_value('prefix') == 'ms' else False,
            "01_suffix_jr": True if r.try_value('suffix') == 'jr' else False,
            "01_suffix_sr": True if r.try_value('suffix') == 'sr' else False,
            "01_suffix_ii": True if r.try_value('suffix') == 'ii' else False,
            "01_suffix_iii": True if r.try_value('suffix') == 'iii' else False,
            "01_suffix_iv": True if r.try_value('suffix') == 'iv' else False,
            "01_firstName": r.try_value('name_first'),
            "01_lastName": r.try_value('name_last'),
            "01_middleName": r.try_value('name_middle'),
            "02_homeAddress": r.try_value('addr'),
            "02_aptLot": self.normalize_unit(r.try_value('unit')),
            "02_cityTown": r.try_value('city'),
            "02_state": r.try_value('state'),
            "02_zipCode": r.try_value('zip'),
            "03_mailAddress": self.format_street_address('mail_addr', 'mail_unit'),
            "03_cityTown": r.try_value('mail_city'),
            "03_state": r.try_value('mail_state'),
            "03_zipCode": r.try_value('mail_zip'),
            "04_dob": r.try_value('dob'),
            "05_telephone": r.try_value('phone'),
            "06_idNumber": r.try_value('identification'),
            "07_party": r.party,
            "08_raceEthnic": '',
            "09_month": r.signed_at_central_tz().strftime('%m') if sig else False,
            "09_day": r.signed_at_central_tz().strftime('%d') if sig else False,
            "09_year": r.signed_at_central_tz().strftime('%Y') if sig else False,
            "A_prefix_mr": True if r.try_value('prev_prefix') == 'mr' else False,
            "A_prefix_mrs": True if r.try_value('prev_prefix') == 'mrs' else False,
            "A_prefix_miss": True if r.try_value('prev_prefix') == 'miss' else False,
            "A_prefix_ms": True if r.try_value('prev_prefix') == 'ms' else False,
            "A_suffix_jr": True if r.try_value('prev_suffix') == 'jr' else False,
            "A_suffix_sr": True if r.try_value('prev_suffix') == 'sr' else False,
            "A_suffix_ii": True if r.try_value('prev_suffix') == 'ii' else False,
            "A_suffix_iii": True if r.try_value('prev_suffix') == 'iii' else False,
            "A_suffix_iv": True if r.try_value('prev_suffix') == 'iv' else False,
            "A_firstName": r.try_value('prev_name_first'),
            "A_lastName": r.try_value('prev_name_last'),
            "A_middleName": r.try_value('prev_name_middle'),
            "B_homeAddress": r.try_value('prev_addr'),
            "B_aptLot": r.try_value('prev_unit'),
            "B_cityTown": r.try_value('prev_city'),
            "B_state": r.try_value('prev_state'),
            "B_zipCode": r.try_value('prev_zip'),
            "D_helper": r.try_value('helper'),
            "signature": sig,
        }
