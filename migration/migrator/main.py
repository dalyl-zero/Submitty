"""Basic migration script to handle the database."""

from collections import OrderedDict
from datetime import datetime
import os
from pathlib import Path
import re

import psycopg2

from sqlalchemy.exc import OperationalError

from . import DIR_PATH, MIGRATIONS_PATH, db
from .loader import load_migrations


def create(args):
    """
    Create a new migration.

    This creates a new migration file for the specified environments. Each
    generated file will have an up() and down() function, but depending on
    the environment, different parameters to the function (e.g. system will
    just have a config variable, master will have config and master DB connection,
    etc.). The file's name is prefixed with a timestamp and then suffixed with
    a user given name, that can only contain alphanumerics or underscores.

    :param args:
    :type args: argparse.Namespace
    """
    now = datetime.now()
    date_args = [now.year, now.month, now.day, now.hour, now.minute, now.second]
    ver = "{:04}{:02}{:02}{:02}{:02}{:02}".format(*date_args)
    filename = "{}_{}".format(ver, args.name)
    check = re.search(r'[^A-Za-z0-9_\-]', filename)
    if check is not None:
        raise ValueError("Name '{}' contains invalid character '{}'".format(
            filename,
            check.group(0)
        ))
    filename += '.py'
    for environment in args.environments:
        parameters = ['config']
        if environment in ['course', 'master']:
            parameters.append('database')
        if environment == 'course':
            parameters.append('semester')
            parameters.append('course')
        with Path(MIGRATIONS_PATH, environment, filename).open('w') as open_file, \
                Path(DIR_PATH, 'data', 'base_migration.py').open() as template_file:
            open_file.write(template_file.read().format(', '.join(parameters)))


def status(args):
    for environment in args.environments:
        if environment in ['master', 'system']:
            params = {
                'driver': args.config.database['database_driver'],
                'dbname': 'submitty',
                'host': args.config.database['database_host'],
                'user': args.config.database['database_user'],
                'password': args.config.database['database_password']
            }
            try:
                database = db.Database(params, environment+'aaa')
                exists = database.engine.dialect.has_table(
                    database.engine,
                    database.migration_table.__tablename__
                )
                if not exists:
                    print('Database for {} does not exist!'.format(environment))
                    continue
                print_status(database)
            except OperationalError:
                print('Could not get status for migrations for {}'.format(environment))
        else:
            params = {
                'driver': args.config.database['database_driver'],
                'host': args.config.database['database_host'],
                'user': args.config.database['database_user'],
                'password': args.config.database['database_password']
            }

            course_dir = Path(args.config.submitty['submitty_data_dir'], 'courses')
            if not course_dir.exists():
                print("Could not find courses directory: {}".format(course_dir))
                continue
            for semester in os.listdir(course_dir):
                for course in os.listdir(os.path.join(course_dir, semester)):
                    cond1 = args.choose_course is not None
                    cond2 = [semester, course] != args.choose_course
                    if cond1 and cond2:
                        continue
                    args.semester = semester
                    args.course = course
                    params['dbname'] = 'submitty_{}_{}aa'.format(semester, course)
                    try:
                        database = db.Database(params, environment)
                        print_status(database)
                    except OperationalError:
                        print('Could not get the status for the migrations '
                              'for {}.{}'.format(semester, course))
                        continue


def print_status(database):
    query = database.session.query(database.migration_table) \
        .order_by(database.migration_table.id).all()
    migrations = []
    for migration in query:
        migrations.append(migration)

    print('{:75s} {}'.format('MIGRATION', 'STATUS'))
    print('-'*83)
    for migration in migrations:
        status = 'UP' if migration.status == 1 else 'DOWN'
        print("{:75s} {}".format(migration.id, status))


def migrate(args):
    """
    Run the migrator in the up (migrate) direction.

    When migrating, the user can pass in arguments to specify to run
    just a single migration, fake the migrations, or only run the first
    migration and mark the rest as done. We can tell we're migrating
    up by checking args.direction.

    :param args: arguments parsed from argparse
    :type args: argparse.Namespace
    """
    args.direction = 'up'
    handle_migration(args)


def rollback(args):
    """
    Run the migrator in the down (rollback) direction.

    This will only rollback one migration at a time. We can tell
    we're rolling back by checking args.direction is down.

    :param args: arguments parsed from argparse
    :type args: argparse.Namespace
    """
    args.direction = 'down'
    handle_migration(args)


def handle_migration(args):
    """
    Run a helper function for handling the migration in both directions.

    Both up and down directions for the migrator contains a fair
    amount of boilerplate type code for creating DB connection for
    the migration, as well as if we're doing a migration for courses,
    iterate through the list of courses that we have

    :param args: arguments parsed from argparse
    :type args: argparse.Namespace
    """
    for environment in args.environments:
        args.course = None
        args.semester = None
        if environment in ['master', 'system']:
            params = {
                'driver': args.config.database['database_driver'],
                'dbname': 'submitty',
                'host': args.config.database['database_host'],
                'user': args.config.database['database_user'],
                'password': args.config.database['database_password']
            }

            print("Running {} migrations for {}...".format(
                args.direction, environment
            ), end="")
            database = db.Database(params, environment)
            migrate_environment(database, environment, args)
            database.close()

        if environment == 'course':
            params = {
                'driver': args.config.database['database_driver'],
                'host': args.config.database['database_host'],
                'user': args.config.database['database_user'],
                'password': args.config.database['database_password']
            }

            course_dir = Path(args.config.submitty['submitty_data_dir'], 'courses')
            if not course_dir.exists():
                print("Could not find courses directory: {}".format(course_dir))
            else:
                for semester in os.listdir(course_dir):
                    for course in os.listdir(os.path.join(course_dir, semester)):
                        if args.choose_course is not None and \
                           [semester, course] != args.choose_course:
                            continue
                        args.semester = semester
                        args.course = course
                        print("Running {} migrations for {}.{}...".format(
                            args.direction, semester, course
                        ), end="")
                        params['dbname'] = 'submitty_{}_{}'.format(semester, course)
                        try:
                            database = db.Database(params, environment)
                            migrate_environment(database, environment, args)
                            database.close()
                        except psycopg2.OperationalError:
                            print("Submitty Database Migration Warning:  "
                                  "Database does not exist for "
                                  "semester={} course={}".format(semester, course))


def migrate_environment(database, environment, args):
    """
    Determine list of migrations/rollback steps that need to be run for environment.

    This function handles the actual business of migrating/rolling back based
    on a passed in environment and connection for that environment (system and master
    have DB connection to master DB and course has DB connection to their own DB).
    This function, given that information then determines the list of migrations
    that exist within the system, compare them against the list of migrations that
    are stored within the DB and if we find migrations that are in the DB, but not
    within the repo, we roll those back before continuing. After that, we now have
    the candidate migration set, which is then used for migrating up or rolling back.
    The candidate migration set is an OrderedDict wherein each value of the dict
    contains the loaded migration file as a module.

    :param connection: connection to the DB
    :param environment: environment we're using for migration step
    :param args: arguments parsed from argparse
    """
    missing_migrations = OrderedDict()
    migrations = load_migrations(MIGRATIONS_PATH / environment)

    # Check if the migration table exists, which it won't on the first time
    # we run the migrator. The initial migration is what creates this table for us.
    exists = database.engine.dialect.has_table(
        database.engine,
        database.migration_table.__tablename__
    )

    changes = False
    if exists:
        query = database.session.query(database.migration_table) \
            .order_by(database.migration_table.id).all()
        for migration in query:
            if migration.id in migrations:
                migrations[migration.id].update({
                    'commit_time': migration.commit_time,
                    'status': migration.status,
                    'db': True,
                    'table': migration
                })
            else:
                missing_migrations[migration['id']] = migration

    if len(missing_migrations) > 0:
        if not changes:
            print()
        print('Removing {} missing migrations:'.format(len(missing_migrations)))
        for key in missing_migrations:
            remove_migration(
                database,
                missing_migrations[key],
                environment,
                args
            )
            changes = True
        print()

    args.fake = args.set_fake if 'set_fake' in args else False
    if args.direction == 'up':
        keys = list(migrations.keys())
        if args.initial is True:
            key = keys.pop(0)
            if not changes:
                print("")
                changes = True
            run_migration(database, migrations[key], environment, args)
            args.fake = True
        for key in keys:
            if migrations[key]['status'] == 0:
                run_migration(database, migrations[key], environment, args)
                if args.single:
                    break
    else:
        for key in reversed(list(migrations.keys())):
            if migrations[key]['status'] == 1:
                run_migration(database, migrations[key], environment, args)
                break

    print("DONE")
    if changes:
        print()


def remove_migration(database, migration, environment, args):
    """Remove migrations that exist on the system, but not within the migrator tool."""
    print("  {}".format(migration['id']))
    file_path = Path(
        args.config.submitty['submitty_install_dir'], 'migrations',
        environment, migration['id'] + '.py'
    )
    if file_path.exists():
        module = load_migration_module(migration['id'], file_path)
        call_func(getattr(module, 'down', noop), database, environment, args)
        file_path.unlink()
    database.session.delete(migration)
    database.session.commit()


def call_func(func, database, environment, args):
    """
    Call a user supplied function with variable number of parameters.

    Depending on the environment that this function is being run under,
    it gets a different list of arguments.
    """
    parameters = [args.config]
    if environment in ['course', 'master']:
        parameters.append(database)
    if environment == 'course':
        parameters.append(args.semester)
        parameters.append(args.course)
    func(*parameters)


def noop(_):
    """Run noop function that does nothing if migration is missing up or down func."""
    pass


def run_migration(database, migration, environment, args):
    """Run the actual migration/rollback function for the migration module."""
    print("  {}{}".format(migration['id'], ' (FAKE)' if args.fake else ''))
    if not args.fake:
        call_func(
            getattr(migration['module'], args.direction, noop),
            database,
            environment,
            args
        )
        database.session.commit()

    status = 1 if args.direction == 'up' else 0
    if migration['table'] is not None:
        database.session.update(migration['table']).values(status=status)
    else:
        database.session.add(
            database.migration_table(id=migration['id'], status=status)
        )
    database.session.commit()