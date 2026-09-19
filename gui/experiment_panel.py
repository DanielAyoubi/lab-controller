from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from devices import DEVICE_TYPES
from experiment import humidity_cycle


def spin_box(minimum, maximum, value, suffix, step=1.0):
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(value)
    box.setSuffix(suffix)
    box.setSingleStep(step)  # how far one click of an arrow, or one arrow key, moves the value
    return box


class ExperimentPanel(QWidget):
    """Build a list of timed steps, then run it. `send` passes a command to the worker."""

    def __init__(self, send):
        super().__init__()
        self.send = send
        self.controls = []  # (device name, control, unit), one table column each
        self.running = False

        self.humid_mfc = QComboBox()
        self.dry_mfc = QComboBox()
        self.total_flow = spin_box(0, 100, 2.0, " L/min", step=0.1)
        self.low = spin_box(0, 100, 0, " %")
        self.high = spin_box(0, 100, 90, " %")
        self.step = spin_box(0.1, 100, 10, " %")
        self.hold = spin_box(0.1, 10000, 30, " min")
        self.start_at = QComboBox()
        self.start_at.addItems(["Lowest (ramp up)", "Highest (ramp down)"])
        self.cycles = QSpinBox()
        self.cycles.setRange(1, 1000)
        self.cycles.setValue(3)
        fill_button = QPushButton("Fill table")
        fill_button.clicked.connect(self.fill_humidity_cycle)

        cycle_form = QFormLayout()
        cycle_form.addRow("Humid air MFC", self.humid_mfc)
        cycle_form.addRow("Dry air MFC", self.dry_mfc)
        cycle_form.addRow("Total flow", self.total_flow)
        cycle_form.addRow("Lowest humid share", self.low)
        cycle_form.addRow("Highest humid share", self.high)
        cycle_form.addRow("Step", self.step)
        cycle_form.addRow("Hold per step", self.hold)
        cycle_form.addRow("Start at", self.start_at)
        cycle_form.addRow("Cycles", self.cycles)
        cycle_form.addRow(fill_button)
        cycle_form.addRow(QLabel("Humid share = % of the total flow sent\nthrough the humid MFC."))
        cycle_group = QGroupBox("Humidity cycle")
        cycle_group.setLayout(cycle_form)
        cycle_group.setMaximumWidth(330)

        self.name = QLineEdit()
        self.name.setPlaceholderText("optional, added to the CSV and PNG file names")
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Experiment name"))
        name_row.addWidget(self.name)

        self.table = QTableWidget()
        self.table.itemChanged.connect(self.update_summary)
        add_button = QPushButton("Add step")
        add_button.clicked.connect(lambda: self.add_step())
        remove_button = QPushButton("Remove step")
        remove_button.clicked.connect(self.remove_step)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_steps)
        self.summary = QLabel()
        self.start_button = QPushButton("Start experiment")
        self.start_button.clicked.connect(self.start_or_stop)
        self.start_button.setEnabled(False)

        table_buttons = QHBoxLayout()
        table_buttons.addWidget(add_button)
        table_buttons.addWidget(remove_button)
        table_buttons.addWidget(clear_button)
        table_buttons.addStretch()
        table_buttons.addWidget(self.summary)
        table_buttons.addWidget(self.start_button)

        steps_layout = QVBoxLayout()
        steps_layout.addLayout(name_row)
        steps_layout.addWidget(QLabel("Steps (an empty cell leaves that setpoint unchanged)"))
        steps_layout.addWidget(self.table)
        steps_layout.addLayout(table_buttons)

        layout = QHBoxLayout(self)
        layout.addWidget(cycle_group)
        layout.addLayout(steps_layout)

    def configure(self, setup):
        self.controls = []
        self.humid_mfc.clear()
        self.dry_mfc.clear()
        for device in setup["devices"]:
            device_class = DEVICE_TYPES[device["type"]]
            for control, unit in device_class.controls.items():
                self.controls.append((device["name"], control, unit))
            if "flow" in device_class.controls:
                self.humid_mfc.addItem(device["name"])
                self.dry_mfc.addItem(device["name"])
        if self.dry_mfc.count() > 1:
            self.dry_mfc.setCurrentIndex(1)

        self.table.setRowCount(0)
        self.table.setColumnCount(1 + len(self.controls))
        headers = ["Hold (min)"] + [f"{name} {control} ({unit})" for name, control, unit in self.controls]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.resizeColumnsToContents()  # the header names are the widest thing in a column
        self.update_summary()

    def add_step(self, step=None):
        # Signals stay blocked until the row is complete, so update_summary never sees half a row.
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        texts = [""] * (1 + len(self.controls))
        if step:
            texts[0] = f"{step['minutes']:g}"
            for column, (name, control, unit) in enumerate(self.controls, start=1):
                if (name, control) in step["setpoints"]:
                    texts[column] = f"{step['setpoints'][(name, control)]:g}"
        for column, text in enumerate(texts):
            self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.blockSignals(False)
        self.update_summary()

    def remove_step(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self.update_summary()

    def clear_steps(self):
        self.table.setRowCount(0)
        self.update_summary()

    def fill_humidity_cycle(self):
        if self.humid_mfc.currentText() == "" or self.humid_mfc.currentText() == self.dry_mfc.currentText():
            QMessageBox.warning(self, "Humidity cycle", "Choose two different MFCs for humid and dry air.")
            return
        if self.low.value() >= self.high.value():
            QMessageBox.warning(self, "Humidity cycle", "The lowest humid share must be below the highest.")
            return
        steps = humidity_cycle(self.humid_mfc.currentText(), self.dry_mfc.currentText(), self.total_flow.value(),
                               self.low.value(), self.high.value(), self.step.value(), self.hold.value(),
                               self.cycles.value(), self.start_at.currentIndex() == 1)
        self.table.setRowCount(0)
        for step in steps:
            self.add_step(step)

    def steps_from_table(self):
        """The table as a list of steps. Raises ValueError, naming the row, if a cell is not a number."""
        steps = []
        for row in range(self.table.rowCount()):
            try:
                setpoints = {}
                for column, (name, control, unit) in enumerate(self.controls, start=1):
                    text = self.table.item(row, column).text().strip()
                    if text:
                        setpoints[(name, control)] = float(text)
                steps.append({"minutes": float(self.table.item(row, 0).text()), "setpoints": setpoints})
            except ValueError:
                raise ValueError(f"Step {row + 1} has a hold time or setpoint that is not a number.")
        return steps

    def update_summary(self):
        minutes = 0
        for row in range(self.table.rowCount()):
            try:
                minutes += float(self.table.item(row, 0).text())
            except ValueError:
                pass
        hours, minutes = divmod(round(minutes), 60)
        self.summary.setText(f"{self.table.rowCount()} steps, {hours} h {minutes} min")

    def start_or_stop(self):
        if self.running:
            self.send(("stop",))
            return
        try:
            steps = self.steps_from_table()
        except ValueError as error:
            QMessageBox.warning(self, "Experiment", str(error))
            return
        if not steps:
            QMessageBox.warning(self, "Experiment", "The step table is empty.")
            return
        self.send(("start", steps, self.name.text()))
        self.show_step(1)

    def set_connected(self, connected):
        self.start_button.setEnabled(connected)
        if not connected:
            self.show_step("")

    def show_step(self, step):
        """Called with the step number from each new data row ("" when no experiment runs)."""
        self.running = step != ""
        # The name is read when the log file opens, so editing it mid-run would change nothing.
        self.name.setEnabled(not self.running)
        if self.running:
            self.start_button.setText(f"Stop experiment (step {step}/{self.table.rowCount()})")
            self.table.selectRow(step - 1)
        else:
            self.start_button.setText("Start experiment")
