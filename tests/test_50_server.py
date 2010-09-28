#!/usr/bin/env python
# -*- coding: utf-8 -*-

from saml2.server import Server, Identifier
from saml2 import server, make_instance
from saml2 import samlp, saml, client, config
from saml2 import s_utils
from saml2.s_utils import OtherError
from saml2.s_utils import do_attribute_statement, factory
from py.test import raises
import shelve
import re

def _eq(l1,l2):
    return set(l1) == set(l2)

class TestServer1():
    def setup_class(self):
        self.server = Server("idp.config")
        
        conf = config.Config()
        try:
            conf.load_file("tests/server.config")
        except IOError:
            conf.load_file("server.config")
        self.client = client.Saml2Client(conf)

    def test_issuer(self):
        issuer = self.server.issuer()
        assert isinstance(issuer, saml.Issuer)
        assert _eq(issuer.keyswv(), ["text","format"])
        assert issuer.format == saml.NAMEID_FORMAT_ENTITY
        assert issuer.text == self.server.conf["entityid"]
        

    def test_assertion(self):
        assertion = s_utils.assertion_factory(
            subject= factory(saml.Subject, text="_aaa",
                                name_id=factory(saml.NameID,
                                    format=saml.NAMEID_FORMAT_TRANSIENT)),
            attribute_statement = do_attribute_statement({
                                    ("","","surName"): ("Jeter",""),
                                    ("","","givenName") :("Derek",""),
                                }),
            issuer=self.server.issuer(),
            )
            
        assert _eq(assertion.keyswv(),['attribute_statement', 'issuer', 'id',
                                    'subject', 'issue_instant', 'version'])
        assert assertion.version == "2.0"
        assert assertion.issuer.text == "urn:mace:example.com:saml:roland:idp"
        #
        assert assertion.attribute_statement
        attribute_statement = assertion.attribute_statement
        assert len(attribute_statement.attribute) == 2
        attr0 = attribute_statement.attribute[0]
        attr1 = attribute_statement.attribute[1]
        if attr0.attribute_value[0].text == "Derek":
            assert attr0.friendly_name == "givenName"
            assert attr1.friendly_name == "surName"
            assert attr1.attribute_value[0].text == "Jeter"
        else:
            assert attr1.friendly_name == "givenName"
            assert attr1.attribute_value[0].text == "Derek"
            assert attr0.friendly_name == "surName"
            assert attr0.attribute_value[0].text == "Jeter"
        # 
        subject = assertion.subject
        assert _eq(subject.keyswv(),["text", "name_id"])
        assert subject.text == "_aaa"
        assert subject.name_id.format == saml.NAMEID_FORMAT_TRANSIENT
        
    def test_response(self):
        response = s_utils.response_factory(
                in_response_to="_012345",
                destination="https:#www.example.com",
                status=s_utils.success_status_factory(),
                assertion=s_utils.assertion_factory(
                    subject = factory( saml.Subject, text="_aaa",
                                        name_id=saml.NAMEID_FORMAT_TRANSIENT),
                    attribute_statement = do_attribute_statement({
                                            ("","","surName"): ("Jeter",""),
                                            ("","","givenName") :("Derek",""),
                                        }),
                    issuer=self.server.issuer(),
                ),
                issuer=self.server.issuer(),
            )
            
        print response.keyswv()
        assert _eq(response.keyswv(),['destination', 'assertion','status', 
                                    'in_response_to', 'issue_instant', 
                                    'version', 'issuer', 'id'])
        assert response.version == "2.0"
        assert response.issuer.text == "urn:mace:example.com:saml:roland:idp"
        assert response.destination == "https:#www.example.com"
        assert response.in_response_to == "_012345"
        #
        status = response.status
        print status
        assert status.status_code.value == samlp.STATUS_SUCCESS

    def test_parse_faulty_request(self):
        authn_request = self.client.authn_request(
                            query_id = "id1",
                            destination = "http://www.example.com",
                            service_url = "http://www.example.org",
                            spentityid = "urn:mace:example.com:saml:roland:sp",
                            my_name = "My real name",
                        )
                        
        intermed = s_utils.deflate_and_base64_encode(authn_request)
        # should raise an error because faulty spentityid
        raises(OtherError, self.server.parse_authn_request, intermed)
        
    def test_parse_faulty_request_to_err_status(self):
        authn_request = self.client.authn_request(
                            query_id = "id1",
                            destination = "http://www.example.com",
                            service_url = "http://www.example.org",
                            spentityid = "urn:mace:example.com:saml:roland:sp",
                            my_name = "My real name",
                        )
                        
        intermed = s_utils.deflate_and_base64_encode(authn_request)
        try:
            self.server.parse_authn_request(intermed)
            status = None
        except OtherError, oe:
            print oe.args
            status = s_utils.error_status_factory(oe)
            
        assert status
        print status
        assert _eq(status.keyswv(), ["status_code", "status_message"])
        assert status.status_message.text == 'Not destined for me!'
        status_code = status.status_code
        assert _eq(status_code.keyswv(), ["status_code","value"])
        assert status_code.value == samlp.STATUS_RESPONDER
        assert status_code.status_code.value == samlp.STATUS_UNKNOWN_PRINCIPAL

    def test_parse_ok_request(self):
        authn_request = self.client.authn_request(
                            query_id = "id1",
                            destination = "http://localhost:8088/sso",
                            service_url = "http://localhost:8087/",
                            spentityid = "urn:mace:example.com:saml:roland:sp",
                            my_name = "My real name",
                        )
                        
        print authn_request
        intermed = s_utils.deflate_and_base64_encode(authn_request)
        response = self.server.parse_authn_request(intermed)
        # returns a dictionary
        print response
        assert response["consumer_url"] == "http://localhost:8087/"
        assert response["id"] == "id1"
        name_id_policy = response["request"].name_id_policy
        assert _eq(name_id_policy.keyswv(), ["format", "allow_create"])
        assert name_id_policy.format == saml.NAMEID_FORMAT_TRANSIENT
        assert response["sp_entity_id"] == "urn:mace:example.com:saml:roland:sp"

    def test_sso_response_with_identity(self):
        name_id = self.server.ident.temporary_nameid()
        resp = self.server.do_response(
                    "http://localhost:8087/",   # consumer_url
                    "id12",                       # in_response_to
                    "urn:mace:example.com:saml:roland:sp", # sp_entity_id
                    { "eduPersonEntitlement": "Short stop"}, # identity
                    name_id
                )
                
        print resp.keyswv()
        assert _eq(resp.keyswv(),['status', 'destination', 'assertion', 
                                    'in_response_to', 'issue_instant', 
                                    'version', 'id', 'issuer'])
        assert resp.destination == "http://localhost:8087/"
        assert resp.in_response_to == "id12"
        assert resp.status
        assert resp.status.status_code.value == samlp.STATUS_SUCCESS
        assert resp.assertion
        assert resp.assertion
        assertion = resp.assertion
        print assertion
        assert assertion.authn_statement
        assert assertion.conditions
        assert assertion.attribute_statement
        attribute_statement = assertion.attribute_statement
        print attribute_statement
        assert len(attribute_statement.attribute) == 1
        attribute = attribute_statement.attribute[0]
        assert len(attribute.attribute_value) == 1
        assert attribute.friendly_name == "eduPersonEntitlement"
        assert attribute.name == "urn:oid:1.3.6.1.4.1.5923.1.1.1.7"
        assert attribute.name_format == "urn:oasis:names:tc:SAML:2.0:attrname-format:uri"
        value = attribute.attribute_value[0]
        assert value.text.strip() == "Short stop"
        assert value.get_type() == "xs:string"
        assert assertion.subject
        assert assertion.subject.name_id
        assert assertion.subject.subject_confirmation
        confirmation = assertion.subject.subject_confirmation
        print confirmation.keyswv()
        print confirmation.subject_confirmation_data
        assert confirmation.subject_confirmation_data.in_response_to == "id12"

    def test_sso_response_without_identity(self):
        resp = self.server.do_response(
                    "http://localhost:8087/",   # consumer_url
                    "id12",                       # in_response_to
                    "urn:mace:example.com:saml:roland:sp", # sp_entity_id
                )
                
        print resp.keyswv()
        assert _eq(resp.keyswv(),['status', 'destination', 'in_response_to', 
                                  'issue_instant', 'version', 'id', 'issuer'])
        assert resp.destination == "http://localhost:8087/"
        assert resp.in_response_to == "id12"
        assert resp.status
        assert resp.status.status_code.value == samlp.STATUS_SUCCESS
        assert resp.issuer.text == "urn:mace:example.com:saml:roland:idp"
        assert not resp.assertion 

    def test_sso_failure_response(self):
        exc = s_utils.MissingValue("eduPersonAffiliation missing")
        resp = self.server.error_response( "http://localhost:8087/", "id12", 
                        "urn:mace:example.com:saml:roland:sp", exc )
                
        print resp.keyswv()
        assert _eq(resp.keyswv(),['status', 'destination', 'in_response_to', 
                                  'issue_instant', 'version', 'id', 'issuer'])
        assert resp.destination == "http://localhost:8087/"
        assert resp.in_response_to == "id12"
        assert resp.status
        print resp.status
        assert resp.status.status_code.value == samlp.STATUS_RESPONDER
        assert resp.status.status_code.status_code.value == \
                                        samlp.STATUS_REQUEST_UNSUPPORTED
        assert resp.status.status_message.text == \
                                        "eduPersonAffiliation missing"
        assert resp.issuer.text == "urn:mace:example.com:saml:roland:idp"
        assert not resp.assertion 

    def test_authn_response_0(self):
        ava = { "givenName": ["Derek"], "surName": ["Jeter"], 
                "mail": ["derek@nyy.mlb.com"]}

        resp_str = self.server.authn_response(ava, 
                    "id1", "http://local:8087/", 
                    "urn:mace:example.com:saml:roland:sp",
                    samlp.NameIDPolicy(format=saml.NAMEID_FORMAT_TRANSIENT,
                                        allow_create="true"),
                    "foba0001@example.com")
                   
        response = samlp.response_from_string("\n".join(resp_str))
        print response.keyswv()
        assert _eq(response.keyswv(),['status', 'destination', 'assertion', 
                        'in_response_to', 'issue_instant', 'version', 
                        'issuer', 'id'])
        print response.assertion[0].keyswv()
        assert len(response.assertion) == 1
        assert _eq(response.assertion[0].keyswv(), ['authn_statement', 
                    'attribute_statement', 'subject', 'issue_instant', 
                    'version', 'issuer', 'conditions', 'id'])
        assertion = response.assertion[0]
        assert len(assertion.attribute_statement) == 1
        astate = assertion.attribute_statement[0]
        print astate
        assert len(astate.attribute) == 3
        
    def test_signed_response(self):
        name_id = self.server.ident.temporary_nameid()
                
        signed_resp = self.server.do_response(
                    "http://lingon.catalogix.se:8087/",   # consumer_url
                    "id12",                       # in_response_to
                    "urn:mace:example.com:saml:roland:sp", # sp_entity_id
                    {"eduPersonEntitlement":"Jeter"},
                    name_id = name_id,
                    sign=True
                )

        print "%s" % signed_resp
        assert signed_resp
        
        # It's the assertions that are signed not the response per se
        assert len(signed_resp.assertion) == 1
        assertion = signed_resp.assertion[0]

        # Since the reponse is created dynamically I don't know the signature
        # value. Just that there should be one
        assert assertion.signature.signature_value.text != ""

#------------------------------------------------------------------------

IDENTITY = {"eduPersonAffiliation": ["staff", "member"],
            "surName": ["Jeter"], "givenName": ["Derek"],
            "mail": ["foo@gmail.com"]}

class TestServer2():
    def setup_class(self):
        try:
            self.server = Server("restrictive_idp.config")
        except IOError, e:
            self.server = Server("tests/restrictive_idp.config")
                
    def test_do_aa_reponse(self):
        aa_policy = self.server.conf.aa_policy()
        print aa_policy.__dict__
        print self.server.conf["service"]
        response = self.server.do_aa_response( "http://example.com/sp/", "aaa",
                        "urn:mace:example.com:sp:1", IDENTITY.copy())

        assert response != None
        assert response.destination == "http://example.com/sp/"
        assert response.in_response_to == "aaa"
        assert response.version == "2.0"
        assert response.issuer.text == "urn:mace:example.com:saml:roland:idpr"
        assert response.status.status_code.value == samlp.STATUS_SUCCESS
        assert response.assertion
        assertion = response.assertion
        assert assertion.version == "2.0"
        subject = assertion.subject
        assert subject.name_id.format == saml.NAMEID_FORMAT_TRANSIENT
        assert subject.subject_confirmation
        subject_confirmation = subject.subject_confirmation
        assert subject_confirmation.subject_confirmation_data.in_response_to == "aaa"
        
