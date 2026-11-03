import serial
import re
import time
from app.infrastructure.hardware.interfaces import RFIDReader


def _detect_reader_type(port: str) -> str:
    """Return 'esp32' if port contains '3', else 'usb' as a heuristic fallback."""
    # Simple heuristic: COM3 / ttyUSB0-like names with "3" or "ESP" → ESP32
    p = port.lower()
    if "esp" in p or "3" in p:
        return "esp32"
    return "usb"


class SerialRFIDReader(RFIDReader):
    """
    RFID Reader implementation that reads card UIDs from one or more serial/USB ports (e.g., COM3, COM4).
    Supports listening to multiple ports simultaneously, handling both USB and ESP32 readers with auto-reconnection.
    Per-port reader type can be specified via reader_types dict, or auto-detected per port.
    """
    RETRY_INTERVAL = 15  # seconds between reconnection attempts for a failed port

    def __init__(self, port: str, baudrate: int = 9600, reader_type: str = "auto",
                 reader_types: dict[str, str] | None = None,
                 baudrates: dict[str, int] | None = None):
        self.ports = [p.strip() for p in port.split(",") if p.strip()]
        self.default_baudrate = baudrate
        self.global_reader_type = reader_type.lower()
        self.reader_types: dict[str, str] = reader_types or {}
        self.baudrates: dict[str, int] = baudrates or {}
        self.sers: dict[str, serial.Serial | None] = {p: None for p in self.ports}
        self._last_retry: dict[str, float] = {p: 0.0 for p in self.ports}
        self.connect()

    def _get_reader_type(self, port: str) -> str:
        """Return the effective reader type for a given port."""
        if port in self.reader_types:
            return self.reader_types[port].lower()
        if self.global_reader_type != "auto":
            return self.global_reader_type
        return _detect_reader_type(port)

    def _baudrate_for(self, port: str) -> int:
        return self.baudrates.get(port, self.default_baudrate)

    def connect(self):
        now = time.monotonic()
        for p in self.ports:
            if self.sers[p] is None:
                if now - self._last_retry[p] < self.RETRY_INTERVAL:
                    continue
                self._last_retry[p] = now
                baud = self._baudrate_for(p)
                try:
                    self.sers[p] = serial.Serial(p, baud, timeout=0.1)
                    self.sers[p].reset_input_buffer()
                    port_type = self._get_reader_type(p)
                    print(f"[RFID] Connected to {port_type.upper()} RFID reader on {p} @ {baud} baud")
                except Exception as e:
                    print(f"[RFID] Failed to connect to serial port {p}: {e}")
                    self.sers[p] = None

    def read_card(self) -> str | None:
        self.connect()

        for p in self.ports:
            ser = self.sers[p]
            if ser is None:
                continue

            try:
                if ser.in_waiting:
                    time.sleep(0.05)
                    data = ser.read(ser.in_waiting)
                    if not data:
                        continue

                    uid = self._decode_data(data, self._get_reader_type(p))
                    if uid:
                        return uid

            except Exception as e:
                print(f"[RFID] Error reading from serial port {p}: {e}")
                try:
                    ser.close()
                except Exception:
                    pass
                self.sers[p] = None

        return None

    def _decode_data(self, data: bytes, reader_type: str) -> str | None:
        """Decode raw serial data to a UID string based on reader type strategy."""
        strategies = []

        if reader_type == "esp32":
            strategies = [self._try_esp32]
        elif reader_type == "usb":
            strategies = [self._try_usb_text, self._try_hex]
        else:  # "auto"
            strategies = [self._try_esp32, self._try_usb_text, self._try_hex]

        for strategy in strategies:
            result = strategy(data)
            if result:
                return result

        return None

    @staticmethod
    def _try_esp32(data: bytes) -> str | None:
        try:
            text = data.decode('utf-8', errors='ignore').strip()
            match = re.search(r'[0-9]+', text)
            if match and len(match.group()) >= 4:
                # Match MFRC522 format: strip leading zeros
                return str(int(match.group()))
        except Exception:
            pass
        return None

    @staticmethod
    def _try_usb_text(data: bytes) -> str | None:
        try:
            decoded = data.decode('utf-8', errors='strict').strip()
            digits = re.sub(r'[^0-9]', '', decoded)
            if not digits or len(digits) < 4:
                return None
            # Convert USB decimal to MFRC522 format, so both produce the same UID
            # for the same physical tag. USB gives 4 bytes (e.g. 85707799 → 0x051BCC17),
            # MFRC522 anticoll returns those 4 bytes reversed + BCC as a 5-byte integer.
            return SerialRFIDReader._usb_to_mfrc522(int(digits))
        except (UnicodeDecodeError, ValueError):
            pass
        return None

    @staticmethod
    def _usb_to_mfrc522(val: int) -> str | None:
        """Convert USB 4-byte decimal to MFRC522 5-byte (incl. BCC) combined integer.
        USB bytes are little-endian; MFRC522 anticoll returns them reversed.
        """
        # Extract 4 bytes big-endian from USB decimal
        b0 = (val >> 24) & 0xFF
        b1 = (val >> 16) & 0xFF
        b2 = (val >> 8) & 0xFF
        b3 = val & 0xFF
        # MFRC522 anticoll returns reversed bytes + BCC
        bcc = b0 ^ b1 ^ b2 ^ b3
        # SimpleMFRC522._uid_to_num uses 5 bytes: uid[0..3] reversed + uid[4] (BCC)
        mfrc_id = (b3 << 32) | (b2 << 24) | (b1 << 16) | (b0 << 8) | bcc
        return str(mfrc_id)

    @staticmethod
    def _try_hex(data: bytes) -> str | None:
        hex_str = data.hex().upper()
        if len(hex_str) >= 4:
            return hex_str
        return None
