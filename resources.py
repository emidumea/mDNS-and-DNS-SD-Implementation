import struct
import socket
import psutil
import time
import wmi
from datetime import datetime
import threading

# Variabile globale pentru selecții și TTL
resurse_selectate = {
    "CPU": True,
    "Memory": True,
    "Temperature": True,
    "Disk": True,
    "Network": True,
}
ttl_actual = 20

# Funcții pentru monitorizare resurse
def monitorizare_cpu():
    return f"{psutil.cpu_percent()}%"

def monitorizare_memorie():
    mem_info = psutil.virtual_memory()
    return f"{mem_info.percent}% ({mem_info.used // (1024**2)} MB)"

def monitorizare_temperatura():
    try:
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        sensors = w.Sensor()
        temperaturi = [float(sensor.Value) for sensor in sensors if sensor.SensorType == u'Temperature']
        if temperaturi:
            return f"{sum(temperaturi) / len(temperaturi):.2f}°C"
        else:
            return "N/A"
    except Exception:
        return "N/A"

def monitorizare_disc():
    disc_info = psutil.disk_usage('/')
    return f"{disc_info.percent}% ({disc_info.used // (1024**3)} GB)"

def monitorizare_retea():
    net_info = psutil.net_io_counters()
    return f"Upload: {net_info.bytes_sent // (1024**2)} MB, Download: {net_info.bytes_recv // (1024**2)} MB"

resurse_disponibile = {
    "CPU": monitorizare_cpu,
    "Memory": monitorizare_memorie,
    "Temperature": monitorizare_temperatura,
    "Disk": monitorizare_disc,
    "Network": monitorizare_retea,
}

def obtine_nume_gazda():
    now = datetime.now()
    return f"Resurse-{now.strftime('%H-%M-%S')}.local"

def obtine_nume_serviciu():
    now = datetime.now()
    return f"_service._dns-sd-{now.strftime('%H-%M-%S')}._udp.local"

def encode_name(name):
    parts = name.split(".")
    encoded = b""
    for part in parts:
        encoded += struct.pack("!B", len(part)) + part.encode() #lungime (1 byte), encode trece in binar
    return encoded + b"\x00" #terminator

def construieste_pachet_dns(nume_serviciu, nume_gazda, ip, port, txt_data, ttl):
    """
    cream un pachet DNS pt publicarea unui serviciu prin mDNS.

    :param nume_serviciu: numele complet al serviciului (ex.: "_resources._tcp.local")
    :param nume_gazda: numele gazdei care oferă serviciul (ex.: "Resurse-01.local")
    :param ip: Adresa IP a gazdei (ex.: "192.168.1.10")
    :param port: Portul la care este disponibil serviciul
    :param txt_data: dictionar cu informații suplimentare (ex.: {"CPU": "35%", "Memorie": "2048MB"})
    :return: un pachet DNS sub forma de bytes
    """
    # HEADER (12 bytes)
    # ---> ID (2 bytes)
    # ---> Flags (2 bytes)
    # ---> Nr intrebari (2 bytes) : 0 intrebari (avem doar raspunsuri)
    # ---> Nr raspunsuri (2 bytes): 4 raspunsuri (PTR, SRV, A, TXT)
    # ---> ID (2 bytes)

    header = struct.pack(
        "!HHHHHH",
        0,  # ID (0 pentru mDNS)
        0x8400,  # Flags: raspuns standard (0x8400)
        0,  # nr intrebari
        4,  # nr răspunsuri (PTR, SRV, A, TXT)
        0,  # nr Authority
        0  # nr Additional
    )

    # ----------------------------- PTR
    ptr_name = encode_name(nume_serviciu)
    ptr_data = encode_name(nume_gazda)
    ptr_record = (
            ptr_name + # ex :b"\x09_resources\x04_tcp\x05local\x00"
            struct.pack("!HHIH", 12, 1, ttl, len(ptr_data)) +  # Type PTR, Class IN, TTL=120
            ptr_data
    )

    # ----------------------------- SRV
    srv_data = struct.pack("!HHH", 0, 0, port) + encode_name(nume_gazda) # Priority (=0), Weight (=0), Port, Target
    srv_record = encode_name(nume_gazda) + struct.pack("!HHIH", 33, 1, ttl, len(srv_data)) + srv_data # pack -> Type SRV, Class IN, TTL=120

    # ----------------------------- A
    ip_data = socket.inet_aton(ip) # converteste ip in binar
    a_record = encode_name(nume_gazda) + struct.pack("!HHIH", 1, 1, ttl, len(ip_data)) + ip_data # pack -> Type A, Class IN, TTL=120

    # ----------------------------- TXT
    txt_entries = [f"{k}={v}".encode() for k, v in txt_data.items()]
    txt_data_encoded = b"".join([struct.pack("!B", len(entry)) + entry for entry in txt_entries])
    txt_record = encode_name(nume_gazda) + struct.pack("!HHIH", 16, 1, ttl, len(txt_data_encoded)) + txt_data_encoded

    return header + ptr_record + srv_record + a_record + txt_record

def actualizeaza_selectii_si_ttl():
    global resurse_selectate, ttl_actual
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 9999))

    while True:
        data, _ = sock.recvfrom(1024)
        mesaj = data.decode("utf-8")
        if mesaj.startswith("TTL:"):
            ttl_actual = int(mesaj.split(":")[1])
            print(f"[resources.py] TTL actualizat: {ttl_actual}")
        elif mesaj.startswith("SELECTII:"):
            selectii = mesaj.split(":")[1]
            resurse_selectate = {resursa: (resursa in selectii.split(",")) for resursa in resurse_selectate}

            # selectam resursele active si le afisam
            resurse_active = [resursa for resursa, selectat in resurse_selectate.items() if selectat]
            print(f"[resources.py] Resurse selectate actualizate: {', '.join(resurse_active)}")

def trimite_pachete_dns(ip, port):
    global ttl_actual, resurse_selectate
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    multicast_group = ('224.0.0.251', 5353)

    while True:
        nume_serviciu = obtine_nume_serviciu()
        nume_gazda = obtine_nume_gazda()
        txt_data = {resursa: resurse_disponibile[resursa]() for resursa, activata in resurse_selectate.items() if activata}
        pachet = construieste_pachet_dns(nume_serviciu, nume_gazda, ip, port, txt_data, ttl_actual)
        sock.sendto(pachet, multicast_group)
        print(f"[resources.py] Trimis pachet DNS-SD: {txt_data} cu TTL={ttl_actual}")
        time.sleep(5)

if __name__ == "__main__":
    ip = "192.168.1.10"
    port = 8080
    threading.Thread(target=actualizeaza_selectii_si_ttl, daemon=True).start()
    trimite_pachete_dns(ip, port)
