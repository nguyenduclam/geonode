# -*- coding: utf-8 -*-
#########################################################################
#
# Copyright (C) 2018 OSGeo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################


import hashlib
import traceback
import psycopg2

from configparser import ConfigParser
import os
import six
import sys

from django.core.management.base import CommandError


MEDIA_ROOT = 'uploaded'
STATIC_ROOT = 'static_root'
STATICFILES_DIRS = 'static_dirs'
TEMPLATE_DIRS = 'template_dirs'
LOCALE_PATHS = 'locale_dirs'
EXTERNAL_ROOT = 'external'


def option(parser):

    # Named (optional) arguments
    parser.add_argument(
        '-c',
        '--config',
        help='Use custom settings.ini configuration file')


def geoserver_option_list(parser):

    # Named (optional) arguments
    parser.add_argument(
        '--geoserver-data-dir',
        dest="gs_data_dir",
        default=None,
        help="Geoserver data directory")

    parser.add_argument(
        '--dump-geoserver-vector-data',
        dest="dump_gs_vector_data",
        action="store_true",
        default=None,
        help="Dump geoserver vector data")

    parser.add_argument(
        '--no-geoserver-vector-data',
        dest="dump_gs_vector_data",
        action="store_false",
        default=None,
        help="Don't dump geoserver vector data")

    parser.add_argument(
        '--dump-geoserver-raster-data',
        dest="dump_gs_raster_data",
        action="store_true",
        default=None,
        help="Dump geoserver raster data")

    parser.add_argument(
        '--no-geoserver-raster-data',
        dest="dump_gs_raster_data",
        action="store_false",
        default=None,
        help="Don't dump geoserver raster data")


class Config(object):

    def __init__(self, options):
        self.load_settings(settings_path=options.get('config'))
        self.load_options(options)

    def load_options(self, options):
        if options.get("gs_data_dir", None):
            self.gs_data_dir = options.get("gs_data_dir")

        if options.get("dump_gs_vector_data", None) is not None:
            self.gs_dump_vector_data = options.get("dump_gs_vector_data")

        if options.get("dump_gs_raster_data", None) is not None:
            self.gs_dump_raster_data = options.get("dump_gs_raster_data")

    def load_settings(self, settings_path):

        if not settings_path:
            raise CommandError("Mandatory option (-c / --config)")

        if not os.path.exists(settings_path):
            raise CommandError("Provided '-c' / '--config' file does not exist.")

        config = ConfigParser()
        config.read(settings_path)

        self.pg_dump_cmd = config.get('database', 'pgdump')
        self.pg_restore_cmd = config.get('database', 'pgrestore')

        self.gs_data_dir = config.get('geoserver', 'datadir')
        self.gs_dump_vector_data = \
            config.getboolean('geoserver', 'dumpvectordata')
        self.gs_dump_raster_data = \
            config.getboolean('geoserver', 'dumprasterdata')

        self.app_names = config.get('fixtures', 'apps').split(',')
        self.dump_names = config.get('fixtures', 'dumps').split(',')


sys.path.append(os.path.join(os.path.dirname(__file__), "lib"))


def get_db_conn(db_name, db_user, db_port, db_host, db_passwd):
    """Get db conn (GeoNode)"""
    db_host = db_host if db_host is not None else 'localhost'
    db_port = db_port if db_port is not None else 5432
    conn = psycopg2.connect(
        "dbname='%s' user='%s' port='%s' host='%s' password='%s'" % (db_name, db_user, db_port, db_host, db_passwd)
    )
    return conn


def patch_db(db_name, db_user, db_port, db_host, db_passwd, truncate_monitoring=False):
    """Apply patch to GeoNode DB"""
    conn = get_db_conn(db_name, db_user, db_port, db_host, db_passwd)
    curs = conn.cursor()

    try:
        curs.execute("ALTER TABLE base_contactrole ALTER COLUMN resource_id DROP NOT NULL;")
        curs.execute("ALTER TABLE base_link ALTER COLUMN resource_id DROP NOT NULL;")
        if truncate_monitoring:
            curs.execute("TRUNCATE monitoring_notificationreceiver CASCADE;")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        traceback.print_exc()

    conn.commit()


def cleanup_db(db_name, db_user, db_port, db_host, db_passwd):
    """Remove spurious records from GeoNode DB"""
    conn = get_db_conn(db_name, db_user, db_port, db_host, db_passwd)
    curs = conn.cursor()

    try:
        curs.execute("DELETE FROM base_contactrole WHERE resource_id is NULL;")
        curs.execute("DELETE FROM base_link WHERE resource_id is NULL;")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        traceback.print_exc()

    conn.commit()


def flush_db(db_name, db_user, db_port, db_host, db_passwd):
    """HARD Truncate all DB Tables"""
    db_host = db_host if db_host is not None else 'localhost'
    db_port = db_port if db_port is not None else 5432
    conn = get_db_conn(db_name, db_user, db_port, db_host, db_passwd)
    curs = conn.cursor()

    try:
        sql_dump = """SELECT tablename from pg_tables where tableowner = '%s'""" % (db_user)
        curs.execute(sql_dump)
        pg_tables = curs.fetchall()
        for table in pg_tables:
            if table[0] == 'br_restoredbackup':
                continue
            print("Flushing Data : " + table[0])
            curs.execute("TRUNCATE " + table[0] + " CASCADE;")

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        traceback.print_exc()

    conn.commit()


def dump_db(config, db_name, db_user, db_port, db_host, db_passwd, target_folder):
    """Dump Full DB into target folder"""
    db_host = db_host if db_host is not None else 'localhost'
    db_port = db_port if db_port is not None else 5432
    conn = get_db_conn(db_name, db_user, db_port, db_host, db_passwd)
    curs = conn.cursor()

    try:
        sql_dump = """SELECT tablename from pg_tables where tableowner = '%s'""" % (db_user)
        curs.execute(sql_dump)
        pg_tables = curs.fetchall()
        for table in pg_tables:
            print("Dumping GeoServer Vectorial Data : {}:{}".format(db_name, table[0]))
            os.system('PGPASSWORD="' + db_passwd + '" ' + config.pg_dump_cmd + ' -h ' + db_host +
                      ' -p ' + str(db_port) + ' -U ' + db_user + ' -F c -b' +
                      ' -t \'"' + str(table[0]) + '"\' -f ' +
                      os.path.join(target_folder, table[0] + '.dump ' + db_name))

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        traceback.print_exc()

    conn.commit()


def restore_db(config, db_name, db_user, db_port, db_host, db_passwd, source_folder):
    """Restore Full DB into target folder"""
    db_host = db_host if db_host is not None else 'localhost'
    db_port = db_port if db_port is not None else 5432
    conn = get_db_conn(db_name, db_user, db_port, db_host, db_passwd)
    # curs = conn.cursor()

    try:
        included_extenstions = ['dump', 'sql']
        file_names = [fn for fn in os.listdir(source_folder)
                      if any(fn.endswith(ext) for ext in included_extenstions)]
        for table in file_names:
            print("Restoring GeoServer Vectorial Data : {}:{} ".format(db_name, os.path.splitext(table)[0]))
            pg_rstcmd = 'PGPASSWORD="' + db_passwd + '" ' + config.pg_restore_cmd + ' -c -h ' + db_host + \
                        ' -p ' + str(db_port) + ' -U ' + db_user + ' --role=' + db_user + \
                        ' -F c -t "' + os.path.splitext(table)[0] + '" ' +\
                        os.path.join(source_folder, table) + ' -d ' + db_name
            os.system(pg_rstcmd)

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        traceback.print_exc()

    conn.commit()


def confirm(prompt=None, resp=False):
    """prompts for yes or no response from the user. Returns True for yes and
    False for no.

    'resp' should be set to the default value assumed by the caller when
    user simply types ENTER.

    >>> confirm(prompt='Create Directory?', resp=True)
    Create Directory? [y]|n:
    True
    >>> confirm(prompt='Create Directory?', resp=False)
    Create Directory? [n]|y:
    False
    >>> confirm(prompt='Create Directory?', resp=False)
    Create Directory? [n]|y: y
    True
    """

    if prompt is None:
        prompt = 'Confirm'

    if resp:
        prompt = '%s [%s]|%s: ' % (prompt, 'y', 'n')
    else:
        prompt = '%s [%s]|%s: ' % (prompt, 'n', 'y')

    while True:
        ans = six.moves.input(prompt)
        if not ans:
            return resp
        if ans not in ['y', 'Y', 'n', 'N']:
            print('please enter y or n.')
            continue
        if ans == 'y' or ans == 'Y':
            return True
        if ans == 'n' or ans == 'N':
            return False


def md5_file_hash(file_path):
    """
    A method generating MD5 hash of the provided file.

    :param file_path: file's path with an extension, which will be opened for reading and generating md5 hash
    :return: hex representation of md5 hash
    """
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
