import sys
import threading
import socket
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QListWidget, QTextEdit, QPushButton, QCheckBox, QSpinBox, QLabel, QHBoxLayout
from PyQt5.QtCore import QTimer, Qt
from discover import servicii_detectate, lock, receptioneaza_servicii, gestioneaza_ttl

class ServiceDiscoveryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Servicii Detectate")
        self.resize(800, 600)

        self.resurse_disponibile = {"CPU": True, "Memory": True, "Temperature": True, "Disk": True, "Network": True}
        self.ttl = 20

        # Widget principal
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Layout principal (vertical)
        self.layout = QVBoxLayout(self.central_widget)

        # Layout pentru resurse monitorizate
        self.checkboxes = {}
        for resursa in self.resurse_disponibile:
            checkbox = QCheckBox(resursa)
            checkbox.setChecked(True)

            #conectam modificarea unui checkbox la metoda care actualizeaza resursele selectate
            checkbox.stateChanged.connect(self.update_resurse_selectate)
            self.checkboxes[resursa] = checkbox
            self.layout.addWidget(checkbox)

        # Control pentru TTL
        ttl_layout = QHBoxLayout()
        ttl_label = QLabel("TTL (secunde):")

        # Configurăm spinbox-ul TTL
        self.ttl_spinbox = QSpinBox()
        self.ttl_spinbox.setRange(10, 10000)
        self.ttl_spinbox.setValue(self.ttl)
        self.ttl_spinbox.setFixedWidth(80)
        self.ttl_spinbox.valueChanged.connect(self.update_ttl)

        ttl_layout.addWidget(ttl_label)
        ttl_layout.addWidget(self.ttl_spinbox)
        ttl_layout.addStretch()
        self.layout.addLayout(ttl_layout) # adaugam in layout-ul principal

        # Lista serviciilor
        self.service_list = QListWidget()
        self.layout.addWidget(self.service_list)

        # Detalii despre serviciul selectat
        self.service_details = QTextEdit()
        self.service_details.setReadOnly(True)
        self.layout.addWidget(self.service_details)


        # Timer pentru actualizare automată
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_service_list)
        self.timer.start(2000)  # Actualizare la fiecare 2 secunde

        # Conectare eveniment pentru selecția din listă
        self.service_list.currentItemChanged.connect(self.display_service_details)

    def refresh_service_list(self):
        # Salvăm elementul selectat
        current_item = self.service_list.currentItem()
        current_service = current_item.text() if current_item else None

        scroll_position = self.service_details.verticalScrollBar().value()

        # Refresh la lista
        self.service_list.clear()
        with lock:
            for nume_serviciu in servicii_detectate:
                self.service_list.addItem(nume_serviciu)

        # Restabilim selectia: daca serviciul inca exista il selectam iar
        if current_service:
            items = self.service_list.findItems(current_service, Qt.MatchExactly)
            if items:
                self.service_list.setCurrentItem(items[0])

        self.service_details.verticalScrollBar().setValue(scroll_position)


    def display_service_details(self, current_item):
        if current_item is None:
            self.service_details.clear()
            return

        scroll_position = self.service_details.verticalScrollBar().value()

        nume_serviciu = current_item.text()
        with lock:
            detalii = servicii_detectate.get(nume_serviciu, {})

        text = f"Serviciu: {nume_serviciu}\n\n"
        for tip, informatii in detalii.items():
            text += f"{tip}:\n"
            for cheie, valoare in informatii.items():
                if cheie != "Expira":
                    text += f"  {cheie}: {valoare}\n"
            text += "\n"

        self.service_details.setText(text)

        self.service_details.verticalScrollBar().setValue(scroll_position)

    def update_resurse_selectate(self):
        """
        Actualizează selecțiile resurselor și trimite mesaj către resources.py.
        """
        selectii = [resursa for resursa, checkbox in self.checkboxes.items() if checkbox.isChecked()]
        mesaj = f"SELECTII:{','.join(selectii)}"
        self.trimite_mesaj_udp(mesaj)

    def update_ttl(self):
        self.ttl = self.ttl_spinbox.value()
        mesaj = f"TTL:{self.ttl}"
        self.trimite_mesaj_udp(mesaj)


    def trimite_mesaj_udp(self, mesaj):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(mesaj.encode("utf-8"), ("127.0.0.1", 9999))

if __name__ == "__main__":
    threading.Thread(target=receptioneaza_servicii, daemon=True).start()
    threading.Thread(target=gestioneaza_ttl, daemon=True).start()

    app = QApplication(sys.argv)
    window = ServiceDiscoveryApp()
    window.show()
    sys.exit(app.exec_())