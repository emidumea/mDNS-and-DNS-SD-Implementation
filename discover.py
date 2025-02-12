import socket
import struct
import threading
import time


MULTICAST_GROUP = '224.0.0.251'  # Adresa multicast pentru mDNS
MULTICAST_PORT = 5353  # Portul standard pentru mDNS

servicii_detectate = {}
lock = threading.Lock()


def decode_dns_packet(packet):
    """
    Decodează un pachet DNS și extrage informațiile despre întrebări și înregistrări.
    """
    def decode_name(data, offset):
        """
        Decodează un nume din format DNS. Returnează numele și noul offset.
        """
        # data -> continutul pachetului, # offset -> poz de la care incepe numele codificat
        labels = []
        while True:
            length = data[offset]
            if length == 0:  # am terminat numele DNS
                offset += 1
                break
            # compresie
            if (length & 0xC0) == 0xC0:  # length = 11 -> inseamna ca e pointer
                # length & 0x3F -> eliminam primii 2 biti (pointerul);
                # << 8 -> deplasam cei 6 biti la stanga cu 8 pozitii sa facem loc urmatorului byte
                # | data[offset + 1] -> adaubam bitul urmator
                pointer = ((length & 0x3F) << 8) | data[offset + 1]
                label, _ = decode_name(data, pointer) # decodeaza numele de la adresa indicata de pointer
                labels.append(label)
                offset += 2
                break
            labels.append(data[offset + 1:offset + 1 + length].decode(errors="ignore"))
            offset += 1 + length
        return ".".join(labels), offset

    try:
        header = packet[:12]
        id_, flags, qd_count, an_count, ns_count, ar_count = struct.unpack("!HHHHHH", header)

        offset = 12
        results = []

        # Procesare întrebări
        queries = []
        for _ in range(qd_count):
            name, offset = decode_name(packet, offset)
            qtype, qclass = struct.unpack("!HH", packet[offset:offset + 4])
            offset += 4
            queries.append((name, qtype, qclass))

        # Procesare înregistrări
        total_records = an_count + ns_count + ar_count
        for _ in range(total_records):
            name, offset = decode_name(packet, offset)
            rtype, rclass, ttl, rdata_length = struct.unpack("!HHIH", packet[offset:offset + 10])
            offset += 10

            if rtype == 1:  # ---------- A Record ---------- (mapeaza un nume la o adresa ip)
                ip = socket.inet_ntoa(packet[offset:offset + 4]) # extragem adresa (binar -> text)
                results.append(("A", name, {"IP": ip, "TTL": ttl}))
            elif rtype == 12:  # ---------- PTR Record ----------
                ptr_name, _ = decode_name(packet, offset)
                results.append(("PTR", name, {"PTR": ptr_name, "TTL": ttl}))
            elif rtype == 33:  # ---------- SRV Record ----------
                priority, weight, port = struct.unpack("!HHH", packet[offset:offset + 6])
                target, _ = decode_name(packet, offset + 6)
                results.append(("SRV", name, {"Priority": priority, "Weight": weight, "Port": port, "Target": target, "TTL": ttl}))
            elif rtype == 16:  # ---------- TXT Record ----------
                txt_data = []
                txt_offset = offset # marcheaza unde incepe sectiunea de date
                while txt_offset < offset + rdata_length:
                    txt_length = packet[txt_offset]
                    txt_offset += 1
                    txt_data.append(packet[txt_offset:txt_offset + txt_length].decode(errors="ignore"))
                    txt_offset += txt_length
                results.append(("TXT", name, {"TXT": txt_data, "TTL": ttl}))

            offset += rdata_length

        return {"queries": queries, "records": results}

    except Exception as e:
        print(f"Eroare la decodificare: {e}")
        return {"queries": [], "records": []}

def actualizeaza_servicii(servicii):
    """
    Actualizează structura de stocare cu noile servicii detectate.
    """
    with lock:
        for tip, nume, detalii in servicii:
            detalii["Expira"] = time.time() + detalii["TTL"]

            # Asociere prin PTR (dacă există)
            if tip == "PTR":
                if nume not in servicii_detectate: # daca nu e in dictionar il adaugam
                    servicii_detectate[nume] = {"PTR": detalii}
                else: # daca exista deja in dictionar, actualizam intrarea existenta
                    servicii_detectate[nume]["PTR"] = detalii
            else: # alte tipuri de inregistrari
                # Găsim serviciul asociat bazat pe PTR
                for ptr_name, inregistrari in servicii_detectate.items():
                    if inregistrari.get("PTR", {}).get("PTR") == nume: # vedem daca serviciul are o inregistrare ptr asociata ce corespunde cu numele actual
                        if tip not in servicii_detectate[ptr_name]: # daca nu exista tipul curent de inregistrare, il adaugam
                            servicii_detectate[ptr_name][tip] = detalii
                        else: # daca exista, il actualizam
                            servicii_detectate[ptr_name][tip].update(detalii)
                        break
                else:
                    # Dacă nu există PTR asociat, tratam ca pe o inregistrare izolata
                    if nume not in servicii_detectate:
                        servicii_detectate[nume] = {} # cream intrare noua
                    servicii_detectate[nume][tip] = detalii # adaugam tipul

def gestioneaza_ttl():
    """
    Elimină periodic înregistrările expirate din structura de stocare.
    """
    while True:
        time.sleep(1)
        with lock:
            acum = time.time()
            de_sters = []
            for nume, inregistrari in list(servicii_detectate.items()):
                tipuri_sterse = []
                for tip, detalii in list(inregistrari.items()):
                    if detalii.get("Expira", 0) <= acum:
                        del inregistrari[tip]
                        tipuri_sterse.append(tip)

                if not inregistrari or "PTR" not in inregistrari: # daca serviciul nu mai are inregistrari
                    de_sters.append(nume) # il adaugam il lista cu servicii de sters

            for nume in de_sters:
                del servicii_detectate[nume]
                print(f"[Notificare] Serviciul '{nume}' a expirat.")

def afiseaza_servicii():
    """
    Afișează serviciile detectate într-un format mai organizat (in consola)
    """
    with lock:
        for nume, inregistrari in servicii_detectate.items():
            if "PTR" in inregistrari:
                ptr = inregistrari["PTR"]
                print(f"Serviciu: {ptr['PTR']} ({nume})")
                print(f"  - PTR: {ptr['PTR']} (TTL: {ptr['TTL']})")

            if "SRV" in inregistrari:
                srv = inregistrari["SRV"]
                print(f"  - SRV: {srv['Priority']} {srv['Weight']} {srv['Port']} {srv['Target']} (TTL: {srv['TTL']})")

            if "A" in inregistrari:
                a = inregistrari["A"]
                print(f"  - A: {a['IP']} (TTL: {a['TTL']})")

            if "TXT" in inregistrari:
                txt = inregistrari["TXT"]
                txt_data = ', '.join(txt['TXT'])
                print(f"  - TXT: {txt_data} (TTL: {txt['TTL']})")

            print()


def receptioneaza_servicii():
    # Configurare socket pentru recepționarea pachetelor mDNS
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', MULTICAST_PORT))

    group = socket.inet_aton(MULTICAST_GROUP)
    mreq = group + socket.inet_aton('0.0.0.0')
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    print("Ascult pentru mesaje...")

    while True:
        try:
            mesaj, addr = sock.recvfrom(4096)
            print(f"[Pachet primit de la {addr}]")

            pachet = decode_dns_packet(mesaj)

            if pachet["queries"]:
                print("[Întrebări primite]:")
                for name, qtype, qclass in pachet["queries"]:
                    print(f"  - Nume: {name}, Tip: {qtype}, Clasă: {qclass}")

            # Procesare răspunsuri
            if pachet["records"]:
                actualizeaza_servicii(pachet["records"])
                print("[Actualizat] Servicii detectate:")
                afiseaza_servicii()

        except Exception as e:
            print(f"Eroare în funcția receptioneaza_servicii: {e}")


