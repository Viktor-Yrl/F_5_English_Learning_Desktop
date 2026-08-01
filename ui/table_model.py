from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtSql import QSqlTableModel

from ui.theme import COLORS


def sql_quote(value: str) -> str:
    return value.replace("'", "''")


class WordTableModel(QSqlTableModel):
    HEADERS = {
        1: "Word",
        2: "Translation",
        3: "Level",
        4: "Category",
        5: "Status",
    }

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        value = super().data(index, role)
        selected_column = self.fieldIndex("learning_selected")
        # Read related cells from the base Qt model. Calling QModelIndex.data()
        # here would call this override again and recurse while the table paints.
        is_learning_selected = selected_column >= 0 and int(
            super().data(self.index(index.row(), selected_column), Qt.ItemDataRole.DisplayRole) or 0
        )

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.DisplayRole and index.column() == 5 and is_learning_selected:
            return "learning"
        if role == Qt.ItemDataRole.ForegroundRole:
            if is_learning_selected:
                return QColor(COLORS["pink"])
            status = super().data(self.index(index.row(), 5), Qt.ItemDataRole.DisplayRole)
            if status == "mastered":
                return QColor(COLORS["green"])
            if status == "review":
                return QColor(COLORS["yellow"])
        return value
