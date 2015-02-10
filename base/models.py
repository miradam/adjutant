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
from django.utils import timezone
from user_store import IdentityManager
from serializers import (NewUserSerializer, NewProjectSerializer,
                         ResetUserSerializer)
from django.conf import settings
from jsonfield import JSONField


class Action(models.Model):
    """Database model representation of the related action."""
    action_name = models.CharField(max_length=200)
    action_data = JSONField(default={})
    cache = JSONField(default={})
    state = models.CharField(max_length=200, default="default")
    valid = models.BooleanField(default=False)
    need_token = models.BooleanField(default=True)
    registration = models.ForeignKey('api_v1.Registration')

    order = models.IntegerField()

    created = models.DateTimeField(default=timezone.now)

    def get_action(self):
        """"""
        data = self.action_data
        return settings.ACTION_CLASSES[self.action_name][0](
            data=data, action_model=self)


class BaseAction(object):
    """Base class for the object wrapping around the database model.
       Setup to allow multiple action types and different internal logic
       per type but built from a single database type.
       - 'required' defines what fields to setup from the data.
       - 'token_fields' defined which fields are needed by this action
         at the token stage."""

    required = []

    token_fields = []

    def __init__(self, data, action_model=None, registration=None,
                 order=None):
        """Build itself around an existing database model,
           or build itself and creates a new database model.
           Sets up required data as fields."""

        for field in self.required:
            field_data = data[field]
            setattr(self, field, field_data)

        if action_model:
            self.action = action_model
        else:
            # make new model and save in db
            action = Action.objects.create(
                action_name=self.__class__.__name__,
                action_data=data,
                registration=registration,
                order=order
            )
            action.save()
            self.action = action

    @property
    def valid(self):
        return self.action.valid

    @property
    def need_token(self):
        return self.action.need_token

    def get_cache(self, key):
        return self.action.cache[key]

    def set_cache(self, key, value):
        self.action.cache[key] = value
        self.action.save()

    def pre_approve(self):
        return self._pre_approve()

    def post_approve(self):
        return self._post_approve()

    def submit(self, token_data):
        return self._submit(token_data)

    def _pre_approve(self):
        raise NotImplementedError

    def _post_approve(self):
        raise NotImplementedError

    def _submit(self, token_data):
        raise NotImplementedError

    def __unicode__(self):
        return self.__class__.__name__


class UserAction(BaseAction):

    def __init__(self, *args, **kwargs):

        if settings.USERNAME_IS_EMAIL:
            try:
                self.required.remove('username')
            except ValueError:
                pass
                # nothing to remove
            super(UserAction, self).__init__(*args, **kwargs)
            self.username = self.email
        else:
            super(UserAction, self).__init__(*args, **kwargs)


class NewUser(UserAction):
    """Setup a new user with a role on the given project.
       Creates the user if they don't exist, otherwise
       if the username and email for the request match the
       existing one, will simply add the project role."""

    required = [
        'username',
        'email',
        'project_id',
        'role'
    ]

    token_fields = ['password']

    def _validate(self):
        # TODO(Adriant): Figure out how to set this up as a generic
        # user store object/module that can handle most of this and
        # be made pluggable down the line.
        id_manager = IdentityManager()

        user = id_manager.find_user(self.username)

        keystone_user = self.action.registration.keystone_user

        if not ("admin" in keystone_user['roles'] or
                keystone_user['project_id'] == self.project_id):
            return ['Project id does not match keystone user project.']

        project = id_manager.get_project(self.project_id)

        if not project:
            return ['Project does exist.']

        if user:
            if user.email == self.email:
                self.action.valid = True
                self.action.need_token = False
                self.action.state = "existing"
                self.action.save()
                return ['Existing user with matching email.']
            else:
                return ['Existing user with non-matching email.']
        else:
            self.action.valid = True
            self.action.save()
            return ['No user present with username']

    def _pre_approve(self):
        return self._validate()

    def _post_approve(self):
        return self._validate()

    def _submit(self, token_data):
        notes = self._validate()

        if self.valid:
            id_manager = IdentityManager()

            if self.action.state == "default":
                user = id_manager.create_user(
                    name=self.username, password=token_data['password'],
                    email=self.email, project_id=self.project_id)
                role = id_manager.find_role(self.role)
                id_manager.add_user_role(user, role, self.project_id)

                notes.append(
                    'User %s has been created, with role %s in project %s.'
                    % (self.username, self.role, self.project_id))
                return notes
            elif self.action.state == "existing":
                user = id_manager.find_user(self.username)
                role = id_manager.find_role(self.role)
                id_manager.add_user_role(user, role, self.project_id)

                notes.append(
                    'Existing user %s has been given role %s in project %s.'
                    % (self.username, self.role, self.project_id))
                return notes
        return notes


class NewProject(UserAction):
    """Similar functionality as the NewUser action,
       but will create the project if valid. Will setup
       the user (existing or new) with the 'default_role'."""

    required = [
        'project_name',
        'username',
        'email'
    ]

    default_roles = ["Member", "project_owner"]

    token_fields = ['password']

    def _validate_project(self):
        id_manager = IdentityManager()

        user = id_manager.find_user(self.username)

        project = id_manager.find_project(self.project_name)

        notes = []

        if user:
            if user.email == self.email:
                self.action.valid = True
                self.action.state = "existing"
                self.action.need_token = False
                self.action.save()
                notes.append("Existing user '%s' with matching email." %
                             self.email)
            else:
                notes.append("Existing user '%s' with non-matching email." %
                             self.username)
        else:
            self.action.valid = True
            self.action.save()
            notes.append("No user present with username '%s'." %
                         self.username)

        if project:
            self.action.valid = False
            self.action.save()
            notes.append("Existing project with name '%s'." %
                         self.project_name)
        else:
            notes.append("No existing project with name '%s'." %
                         self.project_name)

        return notes

    def _validate_user(self):
        id_manager = IdentityManager()

        user = id_manager.find_user(self.username)

        notes = []

        if user:
            if user.email == self.email:
                self.action.valid = True
                self.action.state = "existing"
                self.action.need_token = False
                self.action.save()
                notes.append("Existing user '%s' with matching email." %
                             self.email)
            else:
                notes.append("Existing user '%s' with non-matching email." %
                             self.username)
        else:
            self.action.valid = True
            self.action.save()
            notes.append("No user present with username '%s'." %
                         self.username)

        return notes

    def _pre_approve(self):
        return self._validate_project()

    def _post_approve(self):
        notes = self._validate_project()

        if self.valid:
            id_manager = IdentityManager()

            project = id_manager.create_project(self.project_name)
            # put project_id into action cache:
            self.action.registration.cache['project_id'] = project.id
            self.set_cache('project_id', project.id)
            notes.append("New project '%s' created." % self.project_name)
            return notes
        return notes

    def _submit(self, token_data):
        notes = self._validate_user()

        if self.valid:
            id_manager = IdentityManager()

            project_id = self.get_cache('project_id')
            self.action.registration.cache['project_id'] = project_id
            project = id_manager.get_project(project_id)

            if self.action.state == "default":
                user = id_manager.create_user(
                    name=self.username, password=token_data['password'],
                    email=self.email, project_id=project.id)

                for role in self.default_roles:
                    ks_role = id_manager.find_role(role)
                    id_manager.add_user_role(user, ks_role, project)

                notes.append(
                    "New user '%s' created for project %s with roles: %s" %
                    (self.username, self.project_name, self.default_roles))
                return notes
            elif self.action.state == "existing":
                user = id_manager.find_user(self.username)

                for role in self.default_roles:
                    ks_role = id_manager.find_role(role)
                    id_manager.add_user_role(user, ks_role, project)

                notes.append("Existing user '%s' attached to project %s" +
                             " with roles: %s"
                             % (self.username, self.project_name,
                                self.default_roles))
                return notes
        return notes


class ResetUser(UserAction):
    """Simple action to reset a password for a given user."""

    username = models.CharField(max_length=200)
    email = models.EmailField()

    required = [
        'username',
        'email'
    ]

    token_fields = ['password']

    def _validate(self):
        id_manager = IdentityManager()

        user = id_manager.find_user(self.username)

        if user:
            if user.email == self.email:
                self.action.valid = True
                self.action.save()
                return ['Existing user with matching email.']
            else:
                return ['Existing user with non-matching email.']
        else:
            return ['No user present with username']

    def _pre_approve(self):
        return self._validate()

    def _post_approve(self):
        return self._validate()

    def _submit(self, token_data):
        notes = self._validate()

        if self.valid:
            id_manager = IdentityManager()

            user = id_manager.find_user(self.username)
            id_manager.update_user_password(user, token_data['password'])
            notes.append('User %s password has been changed.' % self.username)
            return notes
        return notes


# A dict of tuples in the format: (<ActionClass>, <ActionSerializer>)
action_classes = {
    'NewUser': (NewUser, NewUserSerializer),
    'NewProject': (NewProject, NewProjectSerializer),
    'ResetUser': (ResetUser, ResetUserSerializer)
}

# setup action classes and serializers for global access
settings.ACTION_CLASSES.update(action_classes)
