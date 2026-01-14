#!/usr/bin/python3
# -*- coding: utf-8 -*-

import gettext
import gi
import locale
import os
import re
import subprocess
import glob

gi.require_version('Gtk', '3.0')
gi.require_version('Nemo', '3.0')

from gi.repository import Nemo, GObject, Gio, GLib, Gtk, Gdk, GdkPixbuf

# i18n
APP = 'ez-folder-color-switcher'
LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

PLUGIN_DESCRIPTION = _('Allows you to change folder colors scanning theme directories dynamically')

import signal
signal.signal(signal.SIGINT, signal.SIG_DFL)

import logging
log_level = os.getenv('LOG_FOLDER_COLOR_SWITCHER', None)
if not log_level:
    log_level = logging.WARNING
else:
    log_level = int(log_level)
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# Mapa de cores para pintar as "bolinhas" do menu.
# Se o script achar uma pasta 'folder-dracula', e 'dracula' não estiver aqui,
# o icone funciona, mas a bolinha do menu fica cinza.
STANDARD_COLORS_HEX = {
    'blue':   '#3584e4',
    'green':  '#33d17a',
    'red':    '#e01b24',
    'orange': '#ff7800',
    'yellow': '#f6d32d',
    'purple': '#9141ac',
    'pink':   '#d56199',
    'grey':   '#9a9996',
    'gray':   '#9a9996',
    'black':  '#3d3d3d',
    'white':  '#ffffff',
    'brown':  '#986a44',
    'cyan':   '#00ffff',
    'teal':   '#008080',
    'magenta':'#ff00ff',
    'indigo': '#4b0082',
    'violet': '#ee82ee',
    'aqua':   '#00ffff',
    'beige':  '#f5f5dc',
    'sand':   '#c2b280',
    'navy':   '#000080',
    'mint':   '#98ff98'
}

class ChangeFolderColorBase(object):
    # Lógica base para tamanhos de ícone (mantida do original para compatibilidade)
    ZOOM_LEVEL_ICON_SIZES = {
        'icon-view'    : [24, 32, 48, 64, 96, 128, 256],
        'list-view'    : [16, 16, 24, 32, 48, 72,  96 ],
        'compact-view' : [16, 16, 18, 24, 36, 48,  96 ]
    }

    ZOOM_LEVELS = {
        'smallest' : 0, 'smaller'  : 1, 'small'    : 2, 'standard' : 3,
        'large'    : 4, 'larger'   : 5, 'largest'  : 6
    }

    KNOWN_DIRECTORIES = {
        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP): 'user-desktop',
        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS): 'folder-documents',
        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD): 'folder-download',
        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC): 'folder-music',
        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES): 'folder-pictures',
        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PUBLIC_SHARE): 'folder-publicshare',
        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES): 'folder-templates',
        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS): 'folder-videos',
        GLib.get_home_dir(): 'user-home'
    }

    def __init__(self):
        self.parent_directory = None
        self.ignore_view_metadata = False
        self.default_view = None
        self.nemo_settings = Gio.Settings.new("org.nemo.preferences")
        self.nemo_settings.connect("changed::ignore-view-metadata", self.on_ignore_view_metadata_changed)
        self.nemo_settings.connect("changed::default-folder-viewer", self.on_default_view_changed)
        self.on_ignore_view_metadata_changed(None)
        self.on_default_view_changed(None)

    def on_ignore_view_metadata_changed(self, settings, key="ignore-view-metadata"):
        self.ignore_view_metadata = self.nemo_settings.get_boolean(key)

    def on_default_view_changed(self, settings, key="default-folder-viewer"):
        self.default_view = self.nemo_settings.get_string(key)

    @staticmethod
    def get_default_view_zoom_level(view="icon-view"):
        zoom_lvl_string = Gio.Settings.new("org.nemo.%s" % view).get_string("default-zoom-level")
        return ChangeFolderColorBase.ZOOM_LEVELS[zoom_lvl_string]

    def get_default_view_icon_size(self):
        zoom_lvl_index = self.get_default_view_zoom_level(self.default_view)
        return ChangeFolderColorBase.ZOOM_LEVEL_ICON_SIZES[self.default_view][zoom_lvl_index]

    @staticmethod
    def get_folder_icon_name(directory):
        return ChangeFolderColorBase.KNOWN_DIRECTORIES.get(directory, 'folder')

    def get_desired_icon_size(self):
        if self.ignore_view_metadata:
            return self.get_default_view_icon_size()
        return self.get_current_view_icon_size()

    def get_current_view_icon_size(self):
        if not self.parent_directory:
            return 64
        info = self.parent_directory.get_location().query_info('metadata::*', 0, None)
        meta_view = info.get_attribute_string('metadata::nemo-default-view')

        if meta_view:
            match = re.search("OAFIID:Nemo_File_Manager_(\\w+)_View", meta_view)
            if match:
                view = match.group(1).lower() + "-view"
            else:
                view = self.default_view
        else:
            view = self.default_view

        if view in self.ZOOM_LEVEL_ICON_SIZES.keys():
            meta_zoom_lvl = info.get_attribute_string("metadata::nemo-%s-zoom-level" % view)
            if not meta_zoom_lvl:
                zoom_level = self.get_default_view_zoom_level(view)
            else:
                zoom_level = int(meta_zoom_lvl)
            return self.ZOOM_LEVEL_ICON_SIZES[view][zoom_level]
        return self.get_default_view_icon_size()

    # Nova função que define diretamente o caminho absoluto, mais confiável para temas customizados
    def set_folder_colors(self, folders, color_data):
        self.parent_directory = folders[0].get_parent_info()
        
        # Se color_data for None, restaura o padrão
        if color_data is None:
            for folder in folders:
                directory = folder.get_location()
                path = directory.get_path()
                directory.set_attribute('metadata::custom-icon', Gio.FileAttributeType.INVALID, 0, 0, None)
                self.refresh_folder(path)
            return

        icon_path = color_data["path"]
        
        for folder in folders:
            if folder.is_gone():
                continue

            directory = folder.get_location()
            path = directory.get_path()
            
            # Converte caminho do arquivo para URI
            icon_uri = GLib.filename_to_uri(icon_path, None)
            
            if icon_uri:
                directory.set_attribute_string('metadata::custom-icon', icon_uri, 0, None)
            
            self.refresh_folder(path)

    def refresh_folder(self, path):
        # touch the folder (to force Nemo/Caja to re-render its icon)
        returncode = subprocess.call(['touch', '-r', path, path])
        if returncode != 0:
            subprocess.call(['touch', path])


# CSS para os botões do menu
css_colors = b"""
.folder-color-switcher-button,
.folder-color-switcher-restore {
    min-height: 16px;
    min-width: 16px;
    padding: 0;
}
.folder-color-switcher-button {
    border-style: solid;
    border-width: 1px;
    border-radius: 1px;
    border-color: transparent;
}
.folder-color-switcher-button:hover {
    border-color: #9c9c9c;
}
.folder-color-switcher-restore {
    background-color: transparent;
}
.folder-color-switcher-restore:hover {
    background-color: rgba(255,255,255,0);
}
"""

provider = Gtk.CssProvider()
provider.load_from_data(css_colors)
screen = Gdk.Screen.get_default()
Gtk.StyleContext.add_provider_for_screen (screen, provider, 600)

class EZFolderColor(ChangeFolderColorBase, GObject.GObject, Nemo.MenuProvider, Nemo.NameAndDescProvider):
    def __init__(self):
        super().__init__()
        logger.info("Initializing dynamic folder-color-switcher extension...")

    def menu_activate_cb(self, menu, color_data, folders):
        self.scale_factor = menu.get_scale_factor()
        self.set_folder_colors(folders, color_data)

    def get_background_items(self, window, current_folder):
        return

    def get_name_and_desc(self):
        return [("ez-folder-color-switcher:::EZ - %s" % PLUGIN_DESCRIPTION)]

    def get_current_theme_colors(self):
        """
        Escaneia o tema atual em busca de icones de pasta coloridos.
        Retorna uma lista de dicionários com metadados da cor.
        """
        icon_theme = Gtk.Settings.get_default().get_property("gtk-icon-theme-name")
        
        # Locais possíveis do tema
        search_paths = [
            os.path.join(os.path.expanduser("~/.local/share/icons"), icon_theme),
            os.path.join("/usr/share/icons", icon_theme)
        ]
        
        valid_theme_path = None
        for p in search_paths:
            if os.path.isdir(p):
                valid_theme_path = p
                break
        
        if not valid_theme_path:
            return []

        # Subpastas onde procurar os ícones (ordem de prioridade)
        # 1. Pasta dedicada 'folder-color' na raiz do tema (fácil para usuários)
        # 2. places/scalable (padrão moderno SVG)
        # 3. places/64 (fallback para PNG)
        subdirs_to_check = ['folder-color', 'places/scalable', 'places/64']
        
        found_colors = {} # Usar dict para evitar duplicatas, chave = cor

        for subdir in subdirs_to_check:
            target_dir = os.path.join(valid_theme_path, subdir)
            if not os.path.isdir(target_dir):
                continue
            
            # Procura por folder-*.svg ou folder-*.png
            files = glob.glob(os.path.join(target_dir, "folder-*.*"))
            
            for f in files:
                filename = os.path.basename(f)
                # Regex para extrair a cor: folder-blue.svg -> blue
                match = re.match(r"^folder-([a-zA-Z0-9]+)\.(svg|png)$", filename)
                
                if match:
                    color_name = match.group(1).lower()
                    
                    # Ignora pastas padrão do sistema que não são cores
                    ignored_names = ['documents', 'download', 'music', 'pictures', 
                                     'publicshare', 'templates', 'videos', 'desktop', 
                                     'home', 'recent', 'remote', 'saved', 'trash']
                    if color_name in ignored_names:
                        continue
                        
                    if color_name not in found_colors:
                        # Tenta achar o Hex da cor para o botão, senão usa cinza
                        hex_color = STANDARD_COLORS_HEX.get(color_name, '#9c9c9c')
                        
                        found_colors[color_name] = {
                            "name": color_name.capitalize(), # Ex: Blue
                            "id": color_name,                # Ex: blue
                            "path": f,                       # Caminho completo
                            "hex": hex_color                 # Ex: #0000FF
                        }

        # Retorna lista ordenada pelo nome
        return sorted(found_colors.values(), key=lambda x: x['name'])

    def get_file_items(self, window, items_selected):
        if not items_selected:
            return

        directories = []
        directories_selected = []

        for item in items_selected:
            if not item.is_directory():
                continue
            if item.get_uri_scheme() != 'file':
                continue
            directories.append(item.get_location())
            directories_selected.append(item)

        if not directories_selected:
            return

        # Escaneia as cores disponíveis no tema atual
        available_colors = self.get_current_theme_colors()
        
        if available_colors:
            logger.debug("Cores encontradas no tema: %s", len(available_colors))
            
            # Cria o menu principal
            item = Nemo.MenuItem(name='ChangeFolderColorMenu::Top')
            
            # Cria o widget com os botões
            item.set_widget_a(self.generate_widget(available_colors, directories_selected))
            item.set_widget_b(self.generate_widget(available_colors, directories_selected))
            
            return Nemo.MenuItem.new_separator('ChangeFolderColorMenu::TopSep'), \
                   item, \
                   Nemo.MenuItem.new_separator('ChangeFolderColorMenu::BotSep')
        else:
            return

    def generate_widget(self, available_colors, items):
        widget = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 1)
        self.scale_factor = widget.get_scale_factor()

        # Botão Restaurar (X)
        button = self.make_button(None)
        button.connect('clicked', self.menu_activate_cb, None, items)
        if len(items) > 1:
            button.set_tooltip_text (_("Restores the color of the selected folders"))
        else:
            button.set_tooltip_text (_("Restores the color of the selected folder"))
        widget.pack_start(button, False, False, 1)

        # Botões das cores encontradas
        for color_data in available_colors:
            button = self.make_button(color_data)
            button.connect('clicked', self.menu_activate_cb, color_data, items)
            
            label_text = _(color_data["name"])
            if len(items) > 1:
                button.set_tooltip_markup (_("Changes the color of the selected folders to %s") % label_text)
            else:
                button.set_tooltip_markup (_("Changes the color of the selected folder to %s") % label_text)
            widget.pack_start(button, False, False, 1)

        widget.show_all()
        return widget

    def make_button(self, color_data):
        button = Nemo.SimpleButton()
        c = button.get_style_context()
        c.add_class("folder-color-switcher-button")

        if color_data is None:
            # Botão de restaurar (ícone de delete)
            image = Gtk.Image(icon_name="edit-delete-symbolic")
            button.set_image(image)
        else:
            # Tenta carregar o template SVG do sistema para pintar a bolinha
            # Se não existir, desenha uma bolinha simples via CSS ou carrega um ícone padrão
            svg_path = "/usr/share/folder-color-switcher/color.svg"
            
            if os.path.exists(svg_path):
                with open(svg_path) as f:
                    svg_content = f.read()
                
                # Substitui a cor no SVG
                # O SVG original do Mint usa #71718e e #4bb4aa como placeholders
                target_hex = color_data["hex"]
                svg_content = svg_content.replace("#71718e", target_hex)
                svg_content = svg_content.replace("#4bb4aa", target_hex)
                
                svg_bytes = str.encode(svg_content)
                stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(svg_bytes))
                pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, 12 * self.scale_factor, 12 * self.scale_factor, True, None)
                surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, self.scale_factor)
                image = Gtk.Image.new_from_surface(surface)
                button.set_image(image)
            else:
                # Fallback se o color.svg não existir: usa um ícone genérico colorido
                # Isso é raro, mas garante que o script não quebre sem o pacote original completo
                image = Gtk.Image(icon_name="image-loading-symbolic") 
                button.set_image(image)

        return button
