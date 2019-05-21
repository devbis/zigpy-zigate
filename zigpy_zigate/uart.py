import asyncio
import logging
import serial
import binascii

import serial_asyncio

LOGGER = logging.getLogger(__name__)


class Gateway(asyncio.Protocol):
    START = b'\x01'
    END = b'\x03'

    def __init__(self, api, connected_future=None):
        self._buffer = b''
        self._connected_future = connected_future
        self._api = api

    def connection_made(self, transport):
        """Callback when the uart is connected"""
        LOGGER.debug("Connection made")
        self._transport = transport
        if self._connected_future:
            self._connected_future.set_result(True)

    def close(self):
        self._transport.close()

    def send(self, data):
        """Send data, taking care of escaping and framing"""
        LOGGER.debug("Send: 0x%s", binascii.hexlify(data).decode())
        checksum = bytes(self._checksum(data))
        frame = self._escape(data + checksum)
        self._transport.write(self.END + frame + self.END)

    def data_received(self, data):
        """Callback when there is data received from the uart"""
        self._buffer += data

        endpos = self._buffer.find(self.END)
        while endpos != -1:
            startpos = self._buffer.rfind(self.START, 0, endpos)
            if startpos != -1 and startpos < endpos:
                frame = self._buffer[startpos:endpos + 1]
                frame = self._unescape(frame)
                length = frame[4:8]
                if len(frame) - 6 != length:
                    LOGGER.warning("Invalid length: %s, data: %s",
                                   length,
                                   len(frame) - 6)
                    continue
                checksum = frame[8]
                if self._checksum(frame) != checksum:
                    LOGGER.warning("Invalid checksum: 0x%s, data: 0x%s",
                                   binascii.hexlify(checksum).decode(),
                                   binascii.hexlify(frame).decode())
                    continue
                LOGGER.debug("Frame received: 0x%s", binascii.hexlify(frame).decode())
                self._api.data_received(frame)
            else:
                LOGGER.error('Malformed packet received, ignore it')
            self._buffer = self._buffer[endpos + 1:]
            endpos = self._buffer.find(self.END)

    def _unescape(self, data):
        flip = False
        decoded = bytearray()
        for b in data:
            if flip:
                flip = False
                decoded.append(b ^ 0x10)
            elif b == 0x02:
                flip = True
            else:
                decoded.append(b)
        return decoded

    def _escape(self, data):
        encoded = bytearray()
        for b in data:
            if b < 0x10:
                encoded.extend([0x02, 0x10 ^ b])
            else:
                encoded.append(b)
        return encoded

    def _checksum(self, frame):
        chcksum = 0
        data = [frame[:4],
                frame[-1],
                frame[10:-1]]
        for arg in data:
            if isinstance(arg, int):
                chcksum ^= arg
                continue
            for x in arg:
                chcksum ^= x
        return chcksum


async def connect(port, baudrate, api, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()

    connected_future = asyncio.Future()
    protocol = Gateway(api, connected_future)

    _, protocol = await serial_asyncio.create_serial_connection(
        loop,
        lambda: protocol,
        url=port,
        baudrate=baudrate,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        xonxoff=False,
    )

    await connected_future

    return protocol
