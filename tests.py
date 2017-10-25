#! /usr/bin/env python
import io
import unittest
import re

import logging
import mock
from django.conf import settings
from django.test import RequestFactory, override_settings

import request_logging
from request_logging.middleware import LoggingMiddleware, DEFAULT_LOG_LEVEL, DEFAULT_COLORIZE, DEFAULT_MAX_BODY_LENGTH

settings.configure()


class BaseLogTestCase(unittest.TestCase):
    def _assert_logged(self, mock_log, expected_entry):
        calls = mock_log.log.call_args_list
        text = "".join([call[0][1] for call in calls])
        self.assertIn( expected_entry, text )

    def _assert_logged_with_level(self, mock_log, level):
        calls = mock_log.log.call_args_list
        called_levels = set(call[0][0] for call in calls)
        self.assertIn(level, called_levels, "{} not in {}".format(level, called_levels))

    def _asset_logged_with_additional_args_and_kwargs(self, mock_log, additional_args, kwargs):
        calls = mock_log.log.call_args_list
        for call_args, call_kwargs in calls:
            additional_call_args = call_args[2:]
            self.assertTrue(additional_args == additional_call_args,
                            "Expected {} to be {}".format(additional_call_args, additional_args))
            self.assertTrue(kwargs == call_kwargs, "Expected {} to be {}".format(call_kwargs, kwargs))

    def _assert_not_logged(self, mock_log, unexpected_entry):
        calls = mock_log.log.call_args_list
        text = " ".join([call[0][1] for call in calls])
        self.assertNotIn(unexpected_entry, text)


@mock.patch.object(request_logging.middleware, "request_logger")
class LogTestCase(BaseLogTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = LoggingMiddleware()

    def test_request_body_logged(self, mock_log):
        body = u"some body"
        request = self.factory.post("/somewhere", data={"file": body})
        self.middleware.process_request(request)
        self._assert_logged(mock_log, body)

    def test_request_binary_logged(self, mock_log):
        body = u"some body"
        datafile = io.StringIO(body)
        request = self.factory.post("/somewhere", data={"file": datafile})
        self.middleware.process_request(request)
        self._assert_logged(mock_log, "(binary data)")

    def test_request_headers_logged(self, mock_log):
        request = self.factory.post("/somewhere",
                                    **{'HTTP_USER_AGENT': 'silly-human'})
        self.middleware.process_request(request)
        self._assert_logged(mock_log, "HTTP_USER_AGENT")

    def test_response_headers_logged(self, mock_log):
        request = self.factory.post("/somewhere")
        response = mock.MagicMock()
        response.get.return_value = 'application/json'
        response._headers = {'test_headers': 'test_headers'}
        self.middleware.process_response(request, response)
        self._assert_logged(mock_log, "test_headers")


@mock.patch.object(request_logging.middleware, "request_logger")
class LoggingContextTestCase(BaseLogTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = LoggingMiddleware()

    def test_request_logging_context(self, mock_log):
        request = self.factory.post("/somewhere")
        self.middleware.process_request(request)
        self._asset_logged_with_additional_args_and_kwargs(mock_log, (), {
            'extra': {
                'request': request,
                'response': None,
            },
        })

    def test_response_logging_context(self, mock_log):
        request = self.factory.post("/somewhere")
        response = mock.MagicMock()
        response.get.return_value = 'application/json'
        response._headers = {'test_headers': 'test_headers'}
        self.middleware.process_response(request, response)
        self._asset_logged_with_additional_args_and_kwargs(mock_log, (), {
            'extra': {
                'request': request,
                'response': response,
            },
        })

    def test_get_logging_context_extensibility(self, mock_log):
        request = self.factory.post("/somewhere")
        self.middleware._get_logging_context = lambda request, response: {
            'args': (1, True, 'Test'),
            'kwargs': {
                'extra': {
                    'REQUEST': request,
                    'middleware': self.middleware,
                },
                'exc_info': True,
            },
        }

        self.middleware.process_request(request)
        self._asset_logged_with_additional_args_and_kwargs(mock_log, (1, True, 'Test'), {
            'extra': {
                'REQUEST': request,
                'middleware': self.middleware,
            },
            'exc_info': True,
        })


class BaseLogSettingsTestCase(BaseLogTestCase):
    def setUp(self):
        body = u"some body"
        datafile = io.StringIO(body)
        self.request = RequestFactory().post(
            "/somewhere",
            data={'file': datafile},
            **{'HTTP_USER_AGENT': 'silly-human'}
        )


@mock.patch.object(request_logging.middleware, "request_logger")
class LogSettingsLogLevelTestCase(BaseLogSettingsTestCase):
    def test_logging_default_debug_level(self, mock_log):
        middleware = LoggingMiddleware()
        middleware.process_request(self.request)
        self._assert_logged_with_level(mock_log, DEFAULT_LOG_LEVEL)

    @override_settings(REQUEST_LOGGING_DATA_LOG_LEVEL=logging.INFO)
    def test_logging_with_customized_log_level(self, mock_log):
        middleware = LoggingMiddleware()
        middleware.process_request(self.request)
        self._assert_logged_with_level(mock_log, logging.INFO)

    @override_settings(REQUEST_LOGGING_DATA_LOG_LEVEL=None)
    def test_invalid_log_level(self, mock_log):
        with self.assertRaises(ValueError):
            LoggingMiddleware()


@mock.patch.object(request_logging.middleware, "request_logger")
class LogSettingsColorizeTestCase(BaseLogSettingsTestCase):
    def test_default_colorize(self, mock_log):
        middleware = LoggingMiddleware()
        middleware.process_request(self.request)
        self.assertEqual(DEFAULT_COLORIZE, self._is_log_colorized(mock_log))

    @override_settings(REQUEST_LOGGING_DISABLE_COLORIZE=False)
    def test_disable_colorize(self, mock_log):
        middleware = LoggingMiddleware()
        middleware.process_request(self.request)
        self.assertFalse(self._is_log_colorized(mock_log))

    @override_settings(REQUEST_LOGGING_DISABLE_COLORIZE='Not a boolean')
    def test_invalid_colorize(self, mock_log):
        with self.assertRaises(ValueError):
            LoggingMiddleware()

    @override_settings(REQUEST_LOGGING_DISABLE_COLORIZE=False)
    def test_disable_colorize(self, mock_log):
        middleware = LoggingMiddleware()
        middleware.process_request(self.request)
        self.assertFalse(self._is_log_colorized(mock_log))

    def _is_log_colorized(self, mock_log):
        reset_code = '\x1b[0m'
        calls = mock_log.log.call_args_list
        logs = " ".join(call[0][1] for call in calls)
        return reset_code in logs


@mock.patch.object(request_logging.middleware, "request_logger")
class LogSettingsMaxLengthTestCase(BaseLogTestCase):
    @override_settings(REQUEST_LOGGING_DISABLE_COLORIZE=False)
    def test_default_max_body_length(self, mock_log):
        factory = RequestFactory()
        middleware = LoggingMiddleware()

        body = DEFAULT_MAX_BODY_LENGTH * "0" + "1"
        request = factory.post("/somewhere", data={"file": body})
        middleware.process_request(request)

        request_body_str = request.body if isinstance(request.body, str) else request.body.decode()
        self._assert_logged(mock_log, re.sub(r'\r?\n', '', request_body_str[:DEFAULT_MAX_BODY_LENGTH]))
        self._assert_not_logged(mock_log, body)

    @override_settings(REQUEST_LOGGING_MAX_BODY_LENGTH=150, REQUEST_LOGGING_DISABLE_COLORIZE=False)
    def test_customized_max_body_length(self, mock_log):
        factory = RequestFactory()
        middleware = LoggingMiddleware()

        body = 150 * "0" + "1"
        request = factory.post("/somewhere", data={"file": body})
        middleware.process_request(request)

        request_body_str = request.body if isinstance(request.body, str) else request.body.decode()
        self._assert_logged(mock_log, re.sub(r'\r?\n', '', request_body_str[:150]))
        self._assert_not_logged(mock_log, body)

    @override_settings(REQUEST_LOGGING_MAX_BODY_LENGTH='Not an int')
    def test_invalid_max_body_length(self, mock_log):
        with self.assertRaises(ValueError):
            LoggingMiddleware()


if __name__ == '__main__':
    unittest.main()

