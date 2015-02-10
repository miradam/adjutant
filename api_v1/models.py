# Copyright (C) 2014 Catalyst IT Ltd
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from django.db import models
from uuid import uuid4
from django.utils import timezone
from jsonfield import JSONField


def hex_uuid():
    return uuid4().hex


class Registration(models.Model):
    """"""
    uuid = models.CharField(max_length=200, default=hex_uuid,
                            primary_key=True)
    # who is this:
    reg_ip = models.GenericIPAddressField()
    keystone_user = JSONField(default={})

    # what do we know about them:
    notes = JSONField(default={})
    errors = JSONField(default={})

    approved = models.BooleanField(default=False)

    completed = models.BooleanField(default=False)

    created = models.DateTimeField(default=timezone.now)
    approved_on = models.DateTimeField(null=True)
    completed_on = models.DateTimeField(null=True)

    # in memory dict to be used for passing data between actions:
    cache = {}

    @property
    def actions(self):
        return self.action_set.order_by('order')

    def to_dict(self):
        actions = []
        for action in self.actions:
            actions.append({
                "action_name": action.action_name,
                "data": action.action_data,
                "valid": action.valid
            })

        return {
            "ip_address": self.reg_ip, "notes": self.notes,
            "approved": self.approved, "completed": self.completed,
            "actions": actions, "uuid": self.uuid
        }


class Token(models.Model):
    """"""

    registration = models.ForeignKey(Registration)
    token = models.CharField(max_length=200, primary_key=True)
    created = models.DateTimeField(default=timezone.now)
    expires = models.DateTimeField()

    def to_dict(self):
        return {
            "registration": self.registration.uuid,
            "token": self.token, "expires": self.expires
        }


class Notification(models.Model):
    """"""

    notes = JSONField(default={})
    registration = models.ForeignKey(Registration)
    created = models.DateTimeField(default=timezone.now)
    acknowledged = models.BooleanField(default=False)

    def to_dict(self):
        return {
            "notes": self.notes,
            "registration": self.registration.uuid,
            "acknowledged": self.acknowledged,
            "created": self.created
        }
