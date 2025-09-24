# Copyright 2024 Dixmit
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from unittest.mock import Mock, patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)


class TestProjectTaskMapping(TransactionCase):
    """Test project task mapping functionality"""

    def setUp(self):
        super().setUp()
        
        # Create test gateway
        self.gateway = self.env["mail.gateway"].create({
            "name": "Test Zulip Gateway",
            "gateway_type": "zulip",
            "zulip_server_url": "https://test.zulipchat.com",
            "zulip_bot_email": "bot@test.zulipchat.com",
            "zulip_api_key": "test_api_key_123456789",
        })
        
        # Create test project and task
        self.project = self.env["project.project"].create({
            "name": "Test Project",
            "active": True,
        })
        
        self.task = self.env["project.task"].create({
            "name": "Test Task",
            "project_id": self.project.id,
            "active": True,
        })
        
        # Create test channel for comparison
        self.channel = self.env["mail.channel"].create({
            "name": "Test Channel",
            "channel_type": "channel",
        })

    def test_create_project_task_mapping(self):
        """Test creating a project task mapping"""
        mapping = self.env["zulip.channel.mapping"].create({
            "gateway_id": self.gateway.id,
            "zulip_stream": "test-stream",
            "zulip_topic": "test-topic",
            "mapping_type": "project_task",
            "project_id": self.project.id,
            "task_id": self.task.id,
        })
        
        self.assertEqual(mapping.mapping_type, "project_task")
        self.assertEqual(mapping.project_id, self.project)
        self.assertEqual(mapping.task_id, self.task)
        self.assertFalse(mapping.odoo_channel_id)
        
        # Check computed name
        expected_name = "test-stream / test-topic → Task: Test Task"
        self.assertEqual(mapping.name, expected_name)

    def test_create_channel_mapping(self):
        """Test creating a channel mapping (existing functionality)"""
        mapping = self.env["zulip.channel.mapping"].create({
            "gateway_id": self.gateway.id,
            "zulip_stream": "test-stream",
            "zulip_topic": "test-topic",
            "mapping_type": "channel",
            "odoo_channel_id": self.channel.id,
        })
        
        self.assertEqual(mapping.mapping_type, "channel")
        self.assertEqual(mapping.odoo_channel_id, self.channel)
        self.assertFalse(mapping.project_id)
        self.assertFalse(mapping.task_id)
        
        # Check computed name
        expected_name = "test-stream / test-topic → Channel: Test Channel"
        self.assertEqual(mapping.name, expected_name)

    def test_mapping_type_onchange(self):
        """Test onchange behavior when switching mapping types"""
        mapping = self.env["zulip.channel.mapping"].new({
            "gateway_id": self.gateway.id,
            "zulip_stream": "test-stream",
            "mapping_type": "channel",
            "odoo_channel_id": self.channel.id,
        })
        
        # Switch to project_task type
        mapping.mapping_type = "project_task"
        mapping._onchange_mapping_type()
        
        # Channel should be cleared
        self.assertFalse(mapping.odoo_channel_id)
        
        # Set project task fields
        mapping.project_id = self.project
        mapping.task_id = self.task
        
        # Switch back to channel type
        mapping.mapping_type = "channel"
        mapping._onchange_mapping_type()
        
        # Project fields should be cleared
        self.assertFalse(mapping.project_id)
        self.assertFalse(mapping.task_id)

    def test_project_onchange(self):
        """Test onchange behavior when changing project"""
        mapping = self.env["zulip.channel.mapping"].new({
            "gateway_id": self.gateway.id,
            "zulip_stream": "test-stream",
            "mapping_type": "project_task",
            "project_id": self.project.id,
            "task_id": self.task.id,
        })
        
        # Create another project
        project2 = self.env["project.project"].create({
            "name": "Test Project 2",
            "active": True,
        })
        
        # Change project
        mapping.project_id = project2
        mapping._onchange_project_id()
        
        # Task should be cleared
        self.assertFalse(mapping.task_id)

    def test_validation_constraints(self):
        """Test validation constraints for project task mappings"""
        
        # Test missing channel for channel mapping
        with self.assertRaises(ValidationError):
            self.env["zulip.channel.mapping"].create({
                "gateway_id": self.gateway.id,
                "zulip_stream": "test-stream",
                "mapping_type": "channel",
                # Missing odoo_channel_id
            })
        
        # Test missing task for project_task mapping
        with self.assertRaises(ValidationError):
            self.env["zulip.channel.mapping"].create({
                "gateway_id": self.gateway.id,
                "zulip_stream": "test-stream",
                "mapping_type": "project_task",
                "project_id": self.project.id,
                # Missing task_id
            })
        
        # Test exclusivity - channel mapping with project fields
        with self.assertRaises(ValidationError):
            self.env["zulip.channel.mapping"].create({
                "gateway_id": self.gateway.id,
                "zulip_stream": "test-stream",
                "mapping_type": "channel",
                "odoo_channel_id": self.channel.id,
                "project_id": self.project.id,  # Should not be set
            })
        
        # Test exclusivity - project_task mapping with channel field
        with self.assertRaises(ValidationError):
            self.env["zulip.channel.mapping"].create({
                "gateway_id": self.gateway.id,
                "zulip_stream": "test-stream",
                "mapping_type": "project_task",
                "task_id": self.task.id,
                "odoo_channel_id": self.channel.id,  # Should not be set
            })

    def test_find_mapping_for_message(self):
        """Test finding mappings for incoming Zulip messages"""
        # Create project task mapping
        task_mapping = self.env["zulip.channel.mapping"].create({
            "gateway_id": self.gateway.id,
            "zulip_stream": "project-stream",
            "zulip_topic": "task-topic",
            "mapping_type": "project_task",
            "project_id": self.project.id,
            "task_id": self.task.id,
        })
        
        # Create channel mapping
        channel_mapping = self.env["zulip.channel.mapping"].create({
            "gateway_id": self.gateway.id,
            "zulip_stream": "chat-stream",
            "zulip_topic": "chat-topic",
            "mapping_type": "channel",
            "odoo_channel_id": self.channel.id,
        })
        
        # Test finding task mapping
        found_mapping = self.env["zulip.channel.mapping"].find_mapping_for_message(
            self.gateway, "project-stream", "task-topic"
        )
        self.assertEqual(found_mapping, task_mapping)
        
        # Test finding channel mapping
        found_mapping = self.env["zulip.channel.mapping"].find_mapping_for_message(
            self.gateway, "chat-stream", "chat-topic"
        )
        self.assertEqual(found_mapping, channel_mapping)
        
        # Test no mapping found
        found_mapping = self.env["zulip.channel.mapping"].find_mapping_for_message(
            self.gateway, "nonexistent-stream", "nonexistent-topic"
        )
        self.assertFalse(found_mapping)

    @patch("mail_gateway_zulip.models.mail_gateway_zulip.MailGatewayZulipService._get_zulip_client")
    def test_message_processing_to_task(self, mock_get_client):
        """Test processing incoming Zulip messages to project tasks"""
        # Create project task mapping
        mapping = self.env["zulip.channel.mapping"].create({
            "gateway_id": self.gateway.id,
            "zulip_stream": "project-stream",
            "zulip_topic": "task-topic",
            "mapping_type": "project_task",
            "project_id": self.project.id,
            "task_id": self.task.id,
        })
        
        # Mock Zulip client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Get initial message count
        initial_message_count = len(self.task.message_ids)
        
        # Process a Zulip message
        zulip_service = self.env["mail.gateway.zulip"]
        zulip_service._process_zulip_message_to_task(
            self.task,
            "Test message from Zulip",
            "user@test.com",
            "Test User",
            "12345",
            self.gateway
        )
        
        # Check that message was created on task
        self.assertEqual(len(self.task.message_ids), initial_message_count + 1)
        
        # Check message content
        new_message = self.task.message_ids[0]  # Latest message
        self.assertIn("Test message from Zulip", new_message.body)
        self.assertEqual(new_message.subtype_id.xml_id, "mail.mt_comment")

    def test_task_message_post_sync(self):
        """Test that messages posted on tasks are synced to Zulip"""
        # Create project task mapping
        mapping = self.env["zulip.channel.mapping"].create({
            "gateway_id": self.gateway.id,
            "zulip_stream": "project-stream",
            "zulip_topic": "task-topic",
            "mapping_type": "project_task",
            "project_id": self.project.id,
            "task_id": self.task.id,
        })
        
        # Mock async sending to avoid actual Zulip API calls
        self.gateway.zulip_async_send = True
        
        # Post message on task
        message = self.task.message_post(
            body="Test message from Odoo task",
            message_type="comment",
        )
        
        # Check that gateway notification was created
        notifications = self.env["mail.notification"].search([
            ("mail_message_id", "=", message.id),
            ("notification_type", "=", "gateway"),
        ])
        
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications.notification_status, "ready")
        self.assertEqual(notifications.gateway_type, "zulip")

    def test_virtual_channel_creation(self):
        """Test virtual channel creation for task sync"""
        # Create project task mapping
        mapping = self.env["zulip.channel.mapping"].create({
            "gateway_id": self.gateway.id,
            "zulip_stream": "project-stream",
            "zulip_topic": "task-topic",
            "mapping_type": "project_task",
            "project_id": self.project.id,
            "task_id": self.task.id,
        })
        
        # Create virtual channel
        virtual_channel = self.task._create_virtual_channel_for_task(mapping)
        
        # Check virtual channel properties
        self.assertIn("Task: Test Task", virtual_channel.name)
        self.assertEqual(virtual_channel.gateway_id, self.gateway)
        self.assertEqual(virtual_channel.gateway_channel_token, "project-stream#task-topic")
        self.assertEqual(virtual_channel.channel_type, "channel")
        
        # Test that calling again returns the same channel
        virtual_channel2 = self.task._create_virtual_channel_for_task(mapping)
        self.assertEqual(virtual_channel, virtual_channel2)

    def test_inactive_project_task_domain(self):
        """Test that inactive projects/tasks are filtered out"""
        # Create inactive project and task
        inactive_project = self.env["project.project"].create({
            "name": "Inactive Project",
            "active": False,
        })
        
        inactive_task = self.env["project.task"].create({
            "name": "Inactive Task",
            "project_id": self.project.id,
            "active": False,
        })
        
        # Test project domain
        project_field = self.env["zulip.channel.mapping"]._fields["project_id"]
        project_domain = project_field.domain
        
        # Should only include active projects
        active_projects = self.env["project.project"].search(project_domain)
        self.assertIn(self.project, active_projects)
        self.assertNotIn(inactive_project, active_projects)
        
        # Test task domain (this is dynamic based on project_id)
        # We can't easily test the dynamic domain, but we can verify the field definition
        task_field = self.env["zulip.channel.mapping"]._fields["task_id"]
        expected_domain = "[('project_id', '=', project_id), ('active', '=', True)]"
        self.assertEqual(task_field.domain, expected_domain)

    def test_unique_mapping_constraint(self):
        """Test that duplicate stream/topic mappings are prevented"""
        # Create first mapping
        self.env["zulip.channel.mapping"].create({
            "gateway_id": self.gateway.id,
            "zulip_stream": "test-stream",
            "zulip_topic": "test-topic",
            "mapping_type": "project_task",
            "project_id": self.project.id,
            "task_id": self.task.id,
        })
        
        # Try to create duplicate mapping (different destination type)
        with self.assertRaises(ValidationError):
            self.env["zulip.channel.mapping"].create({
                "gateway_id": self.gateway.id,
                "zulip_stream": "test-stream",
                "zulip_topic": "test-topic",
                "mapping_type": "channel",
                "odoo_channel_id": self.channel.id,
            })
