# -*- coding: utf-8 -*-
#
# Author: jimin.huang
#
# Created Time: 2015年10月23日 星期五 12时02分25秒
#
'''
    非阻塞的smtp client的测试文件
'''
import client
import mock
import socket
import logging
import smtplib
from tornado.testing import gen_test
from tornado.testing import AsyncTestCase
from tornado.concurrent import Future
from nose.tools import assert_equal


class TestAsyncSMTP(AsyncTestCase):

    @gen_test
    def test_connection(self):
        # TODO:第二个future会触发超时，不知为何
        server = client.AsyncSMTP()
        future_stream = Future()
        future_stream.set_result((202, 'test'))
        server.get_stream = mock.Mock(return_value=future_stream)
        server.receive = mock.Mock(return_value=future_stream)

        code, responses = yield server.connect(host='smtp.163.com')

        assert_equal(code, 202)
        assert_equal(responses, 'test')

    @gen_test
    def test_receive(self):
        # TODO:由于while true的原因不能检查正常输入
        # TODO:未知原因future set result为空时不能中断

        # 异常抛出
        server = client.AsyncSMTP()
        server.stream = mock.Mock()
        server.stream.read_until.side_effect = socket.error

        code, responses = yield server.receive()

        assert code == 'fai'
        assert_equal(responses, ['ed'])

    @gen_test
    def test_send(self):
        server = client.AsyncSMTP()
        server.stream = mock.Mock()
        future_send = Future()
        future_send.set_result((202, 'test'))
        server.stream.write.return_value = future_send
        server.receive = mock.Mock(return_value=future_send)

        yield server.send('test')

        server.stream.write.assert_called_with('test\r\n')

    @gen_test
    def test_ehlo(self):
        server = client.AsyncSMTP()
        future_send = Future()
        future_send.set_result((202, 'test'))
        server.send = mock.Mock(return_value=future_send)
        client._get_hostname = mock.Mock(return_value='test')
        logging.warning = mock.Mock()

        yield server.ehlo()

        server.send.assert_called_with('ehlo [test]')
        logging.warning.assert_called_with('AUTH LOGIN PLAIN not in esmtp features')
        assert_equal(server.esmtp_features, 'test')

    @gen_test
    def test_login(self):
        server = client.AsyncSMTP()
        future_send = Future()
        server.ehlo = mock.Mock(return_value=future_send)
        server.send = mock.Mock(return_value=future_send)
        logging.warning = mock.Mock()

        #正常登录
        future_send.set_result(('235', 'test'))
        yield server.login('test', 'test')

        server.send.assert_called_with('AUTH PLAIN AHRlc3QAdGVzdA==')

        #异常登录
        future_send = Future()
        future_send.set_result(('202', 'test'))
        server.send = mock.Mock(return_value=future_send)
        try:
            yield server.login('test', 'test')
        except smtplib.SMTPAuthenticationError:
            assert True
        else:
            assert False

    @gen_test
    def test_mail(self):
        server = client.AsyncSMTP()
        future_send = Future()
        server.send = mock.Mock(return_value=future_send)
        future_send.set_result(('250', 'test'))

        # 无options
        yield server.mail('test', [])

        server.send.assert_called_with('mail FROM:<test>')

        # 有options
        # code正常250
        yield server.mail('test', ['test'])

        server.send.assert_called_with('mail FROM:<test> test')

        # code 异常421
        future_send = Future()
        server.send = mock.Mock(return_value=future_send)
        future_send.set_result(('421', 'test'))
        server.close = mock.Mock()
        try:
            yield server.mail('test', ['test'])
        except smtplib.SMTPSenderRefused:
            assert True
        else:
            assert False

        assert server.close.called

        # code 异常 非421
        future_send = Future()
        server.send = mock.Mock(return_value=future_send)
        future_send.set_result(('202', 'test'))
        server.rset = mock.Mock(return_value=future_send)
        try:
            yield server.mail('test', ['test'])
        except smtplib.SMTPSenderRefused:
            assert True
        else:
            assert False

        assert server.rset.called
    
    @gen_test
    def test_rset(self):
        server = client.AsyncSMTP()
        future_send = Future()
        server.send = mock.Mock(return_value=future_send)
        future_send.set_result(('235', 'test'))

        # 正常重置
        yield server.rset()

        server.send.assert_called_with('rset')

        # 异常
        logging.debug = mock.Mock()

        server.send.side_effect = smtplib.SMTPServerDisconnected

        yield server.rset()

        logging.debug.assert_called_with('SMTPServerDisconnected')
