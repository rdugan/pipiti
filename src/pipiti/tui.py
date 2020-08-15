import os
import ctypes
import functools
import operator
import enum
import collections.abc
import re
import curses
import npyscreen
from npyscreen import npysThemes, utilNotify
from npyscreen import fmActionFormV2 as actionForm
from npyscreen import wgmultilinetree as mlTree

from amdgpu_pptable import version_detect

MODE_OPEN, MODE_SAVE = (0, 1)


class AMDPPTTheme(npysThemes.TransparentThemeDarkText):
    default_colors = {
        "DEFAULT": "WHITE_ON_DEFAULT",
        "FORMDEFAULT": "WHITE_ON_DEFAULT",
        "NO_EDIT": "CYAN_ON_DEFAULT",
        "STANDOUT": "RED_ON_DEFAULT",
        "IMPORTANT": "YELLOW_ON_DEFAULT",
        "MODIFIED": "RED_ON_DEFAULT",
        "CURSOR": "WHITE_BLACK",
        "CURSOR_INVERSE": "BLACK_WHITE",
        "LABEL": "GREEN_ON_DEFAULT",
        "LABELBOLD": "YELLOW_ON_DEFAULT",
        "CONTROL": "WHITE_ON_DEFAULT",
        "WARNING": "RED_BLACK",
        "CRITICAL": "BLACK_RED",
        "GOOD": "GREEN_BLACK",
        "GOODHL": "GREEN_BLACK",
        "VERYGOOD": "BLACK_GREEN",
        "CAUTION": "YELLOW_BLACK",
        "CAUTIONHL": "BLACK_YELLOW",
    }


class AMDPPTEditor(npyscreen.NPSAppManaged):
    def __init__(self):
        super().__init__()
        self.file_path = None
        self.buf = None
        self.orig_buf = None
        self.pptables = None
        self.tree_form = None
        self.tree_data = None

    def has_active_form(self):
        return hasattr(self, "_THISFORM")

    def parse(self):
        self.pptables = version_detect.parse(self.buf)
        self.tree_data = AMDPPTTreeData(
            ignore_root=False, annotation="AMDGPU PowerPlay Table ", content=" "
        )
        for name, table in self.pptables._asdict().items():
            self.tree_data.append_row(name, table)

        self.tree_form.tree_widget.values = self.tree_data
        self.tree_form.name = self.file_path

    def revert(self):
        self.buf = bytearray(self.orig_buf)
        self.parse()

    def load(self, path):
        try:
            with open(path, "rb") as f:
                self.orig_buf = f.read()

        except Exception:
            utilNotify.notify_confirm(
                title="Error", message=f"Unable to open file {self.file_path}"
            )

        self.revert()

    def save(self, path):
        try:
            with open(path, "wb") as f:
                f.write(self.buf)

            self.orig_buf = bytearray(self.buf)
            self.revert()

        except Exception:
            utilNotify.notify_confirm(
                title="Error", message=f"Unable to save file {self.file_path}"
            )

    def onStart(self):
        npyscreen.setTheme(AMDPPTTheme)
        self.tree_form = self.addForm("MAIN", AMDPPTTreeForm, name=self.file_path)

        max_x, max_y = self.tree_form._max_physical()
        columns = min(80, max_y)
        lines = 12
        pos_x = min(10, int(max(0, (max_y - 80)) / 2))
        pos_y = 2

        self.file_form = self.addForm(
            "FILE",
            AMDPPTFileForm,
            show_atx=pos_x,
            show_aty=pos_y,
            lines=lines,
            columns=columns,
        )

        self.show_load_form()
        if not self.file_path:
            self.exit_application()

    def show_file_form(self, mode=None):
        self.file_form.name = "Save..." if mode == MODE_SAVE else "Open..."
        self.file_form.mode = mode
        self.file_form.display()
        self.file_form.edit()

    def show_load_form(self):
        self.show_file_form(MODE_OPEN)

    def show_save_form(self):
        self.show_file_form(MODE_SAVE)

    def exit_application(self):
        self.setNextForm(None)
        if self.has_active_form():
            self.switchFormNow()


class AMDPPTTreeWidget(mlTree.MLTreeAnnotatedEditable):
    def check_line(self, line):
        if not line.text_value:
            return False
        else:
            tree_data = line._tree_real_value
            try:
                # type check and save to pptable/buffer via callback
                tree_data.edit_func(tree_data.record_type(line.text_value))
            except ValueError:
                return False

            return True


class AMDPPTFileForm(actionForm.ActionFormV2):
    def __init__(self, mode=MODE_OPEN, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode

    @property
    def mode(self):
        return self._mode if hasattr(self, "_mode") else None

    @mode.setter
    def mode(self, mode):
        self._mode = mode if mode in (MODE_OPEN, MODE_SAVE) else MODE_OPEN

    def create(self):
        self.file_widget = self.add(
            npyscreen.TitleFilename, name="File:", begin_entry_at=8
        )

    def on_ok(self):
        file_path = self.file_widget.value
        if self.mode == MODE_OPEN and not os.path.exists(file_path):
            utilNotify.notify_confirm(
                title="Error", message="Selected path does not exist."
            )
            self.DISPLAY()
            self.edit()
        elif os.path.isdir(file_path):
            utilNotify.notify_confirm(
                title="Error", message="Selected path is not a file."
            )
            self.DISPLAY()
            self.edit()
        else:
            app = self.parentApp
            app.file_path = file_path

            if self.mode == MODE_OPEN:
                app.load(app.file_path)
            else:
                app.save(app.file_path)

            self.editing = False

    def on_cancel(self):
        self.editing = False


class AMDPPTTreeForm(npyscreen.FormBaseNewWithMenus):
    MENU_KEY = "^X"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget = self._NMDisplay._DisplayArea._menuListWidget
        widget.add_handlers(
            {ord("x"): widget.h_exit_escape, curses.ascii.ESC: widget.h_exit_escape}
        )

    def create(self):
        self.main_menu = self.add_menu(
            name="Main Menu", shortcut=self.__class__.MENU_KEY
        )
        self.main_menu.addItemsFromList(
            [
                ("Open...", self.parentApp.show_load_form, "^O"),
                ("Revert", self.parentApp.revert, "^R"),
                ("Save...", self.parentApp.show_save_form, "^S"),
                ("Exit Application", self.parentApp.exit_application, "^K"),
            ]
        )
        self.tree_widget = self.add(
            AMDPPTTreeWidget, color="NO_EDIT", highlight_color="STANDOUT"
        )
        self.tree_widget.annotation_padding = 32


# extend TreeData class to include row builder
class AMDPPTTreeData(npyscreen.TreeData):
    @property
    def record_type(self):
        return self._record_type if hasattr(self, "_record_type") else None

    @record_type.setter
    def record_type(self, record_type):
        self._record_type = record_type

    @staticmethod
    def type_label(type):
        if hasattr(type, "wrapped_type"):
            return AMDPPTTreeData.type_label(type.wrapped_type)
        elif issubclass(type, ctypes.Array):
            return f"{type._type_.__name__}[{type._length_}]"
        else:
            return type.__name__

    @staticmethod
    def short_type_label(type):
        return re.sub("struct_+", "", AMDPPTTreeData.type_label(type))

    def append_row(self, name, obj, edit_func=None):
        tree_data = self.new_child(expanded=False, annotation=name)
        obj_type = type(obj)

        if isinstance(obj, collections.abc.MutableMapping):
            tree_data.set_content(self.short_type_label(obj_type))

            for key, value in obj.items():
                field_name = key.name if isinstance(key, enum.Enum) else key
                tree_data.append_row(
                    f"{name}[{field_name}]",
                    value,
                    functools.partial(operator.setitem, obj, key),
                )

        elif isinstance(obj, ctypes.Structure):
            tree_data.set_content(self.short_type_label(obj_type))

            for field_name, field_value in obj_type._fields_:
                tree_data.append_row(
                    field_name,
                    getattr(obj, field_name),
                    functools.partial(setattr, obj, field_name),
                )

        elif isinstance(obj, ctypes.Array):
            tree_data.set_content(self.short_type_label(obj_type))

            for i in range(len(obj)):
                tree_data.append_row(
                    f"{name}[{i}]", obj[i], functools.partial(operator.setitem, obj, i)
                )

        else:
            tree_data.record_type = obj_type
            tree_data.edit_func = edit_func
            tree_data.editable = True
            tree_data.set_content(str(obj))


def main():
    App = AMDPPTEditor()
    App.run()


if __name__ == "__main__":
    main()
