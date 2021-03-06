import atexit
import glob
import shutil
import urllib2

import sys

from mc_solr.constants import *
from mc_solr.utils import *

logger = create_logger(__name__)

__solr_pid = None

if compare_versions(java_version(), MC_SOLR_MIN_JAVA_VERSION) < 0:
    raise Exception("Java is too old (expected: %s, actual: %s)" % (MC_SOLR_MIN_JAVA_VERSION, java_version()))


def __solr_path(dist_directory=MC_DIST_DIR, solr_version=MC_SOLR_VERSION):
    """Return path to where Solr distribution should be located."""
    dist_path = resolve_absolute_path(name=dist_directory, must_exist=True)
    solr_directory = "solr-%s" % solr_version
    solr_path = os.path.join(dist_path, solr_directory)
    return solr_path


def __solr_installing_file_path(dist_directory=MC_DIST_DIR, solr_version=MC_SOLR_VERSION):
    """Return path to file which denotes that Solr is being installed (and thus serves as a lock file)."""
    solr_path = __solr_path(dist_directory=dist_directory, solr_version=solr_version)
    return os.path.join(solr_path, MC_PACKAGE_INSTALLING_FILE)


def __solr_installed_file_path(dist_directory=MC_DIST_DIR, solr_version=MC_SOLR_VERSION):
    """Return path to file which denotes that Solr has been installed."""
    solr_path = __solr_path(dist_directory=dist_directory, solr_version=solr_version)
    return os.path.join(solr_path, MC_PACKAGE_INSTALLED_FILE)


def __solr_dist_url(solr_version=MC_SOLR_VERSION):
    """Return URL to download Solr from."""
    solr_dist_url = "https://archive.apache.org/dist/lucene/solr/%(solr_version)s/solr-%(solr_version)s.tgz" % {
        "solr_version": solr_version,
    }
    return solr_dist_url


def __solr_is_installed(dist_directory=MC_DIST_DIR, solr_version=MC_SOLR_VERSION):
    """Return True if Solr is installed in distribution path."""
    solr_path = __solr_path(dist_directory=dist_directory, solr_version=solr_version)
    installed_file_path = __solr_installed_file_path(dist_directory=dist_directory, solr_version=solr_version)

    if os.path.isfile(installed_file_path):
        if os.path.isfile(os.path.join(solr_path, "README.txt")):
            return True
        else:
            logger.warn(
                "Solr distribution was not found at path '%s' even though it was supposed to be there." % solr_path)
            os.unlink(installed_file_path)

    return False


def __install_solr(dist_directory=MC_DIST_DIR, solr_version=MC_SOLR_VERSION):
    """Install Solr to distribution directory; lock directory before installing and unlock afterwards."""
    if __solr_is_installed(dist_directory=dist_directory, solr_version=solr_version):
        raise Exception("Solr %s is already installed in distribution directory '%s'." % (
            solr_version, dist_directory
        ))

    solr_path = __solr_path(dist_directory=dist_directory, solr_version=solr_version)

    logger.info("Creating Solr directory...")
    mkdir_p(solr_path)

    installing_file_path = __solr_installing_file_path(dist_directory=dist_directory, solr_version=solr_version)

    logger.info("Locking Solr directory for installation...")
    lock_file(installing_file_path, timeout=MC_INSTALL_TIMEOUT)

    # Waited for concurrent installation to finish?
    if __solr_is_installed(dist_directory=dist_directory, solr_version=solr_version):
        logger.info("While waiting for Solr directory to unlock, Solr got installed to said directory.")
        return

    solr_dist_url = __solr_dist_url(solr_version=solr_version)

    logger.info("Downloading Solr %s from %s..." % (solr_version, solr_dist_url))
    solr_tarball_dest_path = download_file_to_temp_path(solr_dist_url)

    logger.info("Extracting %s to %s..." % (solr_tarball_dest_path, solr_path))
    extract_tarball_to_directory(archive_file=solr_tarball_dest_path,
                                 dest_directory=solr_path,
                                 strip_root=True)

    # Solr needs its .war extracted first before ZkCLI is usable
    jetty_home_path = __jetty_home_path(dist_directory=dist_directory, solr_version=solr_version)
    solr_war_dest_dir = os.path.join(jetty_home_path, "solr-webapp", "webapp")

    # Solr 5.5.2+ already has the .war extracted
    if not os.path.exists(os.path.join(solr_war_dest_dir, "index.html")):
        solr_war_path = os.path.join(jetty_home_path, "webapps", "solr.war")
        if not os.path.isfile(solr_war_path):
            raise Exception("Solr's .war file does not exist at path %s" % solr_war_path)

        solr_war_dest_dir = os.path.join(jetty_home_path, "solr-webapp", "webapp")
        logger.info("Extracting solr.war at '%s' to '%s'..." % (solr_war_path, solr_war_dest_dir))
        mkdir_p(solr_war_dest_dir)
        extract_zip_to_directory(archive_file=solr_war_path, dest_directory=solr_war_dest_dir)

    logger.info("Creating 'installed' file...")
    installed_file_path = __solr_installed_file_path(dist_directory=dist_directory, solr_version=solr_version)
    lock_file(installed_file_path)

    logger.info("Removing lock file...")
    unlock_file(installing_file_path)

    if not __solr_is_installed(dist_directory=dist_directory, solr_version=solr_version):
        raise Exception("I've done everything but Solr is still not installed.")


def __solr_home_path(solr_home_dir=MC_SOLR_HOME_DIR):
    """Return path to Solr home (with collection subdirectories)."""
    solr_home_path = resolve_absolute_path(name=solr_home_dir, must_exist=True)
    return solr_home_path


def __jetty_home_path(dist_directory=MC_DIST_DIR, solr_version=MC_SOLR_VERSION):
    solr_path = __solr_path(dist_directory=dist_directory, solr_version=solr_version)

    jetty_home_path = None
    jetty_home_dir_candidates = [
        # Solr 4
        "example",

        # Solr 5+
        "server",
    ]
    for candidate_dir in jetty_home_dir_candidates:
        candidate_path = os.path.join(solr_path, candidate_dir)
        if os.path.exists(os.path.join(candidate_path, "start.jar")):
            logger.debug("jetty.home found: %s" % candidate_path)
            jetty_home_path = candidate_path
    if jetty_home_path is None:
        raise Exception("Unable to locate jetty.home among candidates: %s" % str(jetty_home_dir_candidates))

    return jetty_home_path


def __collections_path(solr_home_dir=MC_SOLR_HOME_DIR):
    solr_home_path = __solr_home_path(solr_home_dir=solr_home_dir)
    collections_path = os.path.join(solr_home_path, "collections/")
    if not os.path.isdir(collections_path):
        raise Exception("Collections directory does not exist at path '%s'" % collections_path)
    logger.debug("Collections path: %s" % collections_path)
    return collections_path


def __collections(solr_home_dir=MC_SOLR_HOME_DIR):
    """Return dictionary with names and absolute paths to Solr collections."""
    collections = {}
    collections_path = __collections_path(solr_home_dir)
    collection_names = os.listdir(collections_path)
    logger.debug("Files in collections directory: %s" % collection_names)
    for name in collection_names:
        if not (name.startswith("_") or name.startswith(".")):
            full_path = os.path.join(collections_path, name)
            if os.path.isdir(full_path):

                collection_conf_path = os.path.join(full_path, "conf")
                if not os.path.isdir(collection_conf_path):
                    raise Exception("Collection configuration path for collection '%s' does not exist." % name)

                collections[name] = full_path

    return collections


def __standalone_data_dir(base_data_dir=MC_SOLR_BASE_DATA_DIR):
    """Return data directory for a standalone instance."""
    if not os.path.isdir(base_data_dir):
        raise Exception("Solr data directory '%s' does not exist." % base_data_dir)
    return os.path.join(base_data_dir, "mediacloud-standalone")


def __shard_data_dir(shard_num, base_data_dir=MC_SOLR_BASE_DATA_DIR):
    """Return data directory for a shard."""
    if shard_num < 1:
        raise Exception("Shard number must be 1 or greater.")
    if not os.path.isdir(base_data_dir):
        raise Exception("Solr data directory '%s' does not exist." % base_data_dir)

    shard_subdir = "mediacloud-cluster-shard-%d" % shard_num
    return os.path.join(base_data_dir, shard_subdir)


def __shard_port(shard_num, starting_port=MC_SOLR_CLUSTER_STARTING_PORT):
    """Return port on which a shard should listen to."""
    if shard_num < 1:
        raise Exception("Shard number must be 1 or greater.")
    return starting_port + shard_num - 1


def __raise_if_old_shards_exist():
    """Raise exception with migration instructions if old shard directories exist already."""

    pwd = resolve_absolute_path(".")
    old_shards = glob.glob(pwd + "/mediacloud-shard-*")

    if len(old_shards) == 0:
        # No old shards to migrate
        return

    num_shards = 0
    for old_shard_path in old_shards:
        old_shard_dir = os.path.basename(old_shard_path)

        old_shard_num = re.search(r'^mediacloud-shard-(\d+?)$', old_shard_dir)
        if old_shard_num is None:
            raise Exception("Unable to parse shard number for old shard directory '%s'" % old_shard_dir)
        old_shard_num = int(old_shard_num.group(1))

        num_shards = max(num_shards, old_shard_num)

    exc_message = "Old shards were found at paths:\n\n"
    for old_shard_path in old_shards:
        exc_message += "* %s\n" % old_shard_path

    exc_message += "\n"
    exc_message += "Please migrate them by running:\n"
    exc_message += "\n"
    exc_message += "cd %s\n" % pwd
    exc_message += "\n"
    exc_message += "# Create empty new shard directory structure for each shard:\n"
    for shard_num in range(1, num_shards + 1):
        exc_message += ("./run_solr_shard.py --shard_num %(shard_num)d --shard_count %(shard_count)d " +
                        "|| echo \"It's fine to fail at this point.\"\n") % {
                           "shard_num": shard_num,
                           "shard_count": num_shards,
                       }

    exc_message += "\n"
    exc_message += "# Move data from old shards to new ones\n"
    for shard_num in range(1, num_shards + 1):
        shard_solr_path = "mediacloud-shard-%d/solr/" % shard_num
        shard_collection_paths = glob.glob(shard_solr_path + "/collection*")
        if len(shard_collection_paths) == 0:
            raise Exception("No collections found in shard '%d'" % shard_num)
        for collection_path in shard_collection_paths:
            collection_name = os.path.basename(collection_path)

            src_collection_data_path = os.path.join(shard_solr_path, collection_name, "data")
            if not os.path.isdir(src_collection_data_path):
                raise Exception("Source data directory '%s' does not exist." % src_collection_data_path)

            dst_shard_data_dir = __shard_data_dir(shard_num=shard_num)
            dst_collection_data_path = os.path.join(dst_shard_data_dir, collection_name, "data")
            if os.path.isdir(dst_collection_data_path):
                raise Exception("Destination data directory '%s' already exists." % dst_collection_data_path)

            exc_message += "mv %(src_collection_data_dir)s %(dst_collection_data_dir)s\n" % {
                "src_collection_data_dir": src_collection_data_path,
                "dst_collection_data_dir": dst_collection_data_path,
            }
        exc_message += "\n"

    exc_message += "# Remove old shards\n"
    for shard_num in range(1, num_shards + 1):
        exc_message += "rm -rf mediacloud-shard-%d/\n" % shard_num

    raise Exception(exc_message)


def __run_solr_zkcli(zkcli_args,
                     zookeeper_host=MC_SOLR_CLUSTER_ZOOKEEPER_HOST,
                     zookeeper_port=MC_SOLR_CLUSTER_ZOOKEEPER_PORT,
                     dist_directory=MC_DIST_DIR,
                     solr_version=MC_SOLR_VERSION):
    """Run Solr's zkcli.sh helper script."""
    solr_path = __solr_path(dist_directory=dist_directory, solr_version=solr_version)

    jetty_home_path = __jetty_home_path(dist_directory=dist_directory, solr_version=solr_version)

    log4j_properties_path = None
    log4j_properties_expected_paths = [
        # Solr 4.6
        os.path.join(jetty_home_path, "cloud-scripts", "log4j.properties"),

        # Solr 4.10+
        os.path.join(jetty_home_path, "scripts", "cloud-scripts", "log4j.properties"),
    ]

    for expected_path in log4j_properties_expected_paths:
        if os.path.isfile(expected_path):
            log4j_properties_path = expected_path
            break

    if log4j_properties_path is None:
        raise Exception("Unable to find log4j.properties file for zkcli.sh script in paths: %s" %
                        str(log4j_properties_expected_paths))

    if not tcp_port_is_open(hostname=zookeeper_host, port=zookeeper_port):
        raise Exception("ZooKeeper is not running at %s:%d." % (zookeeper_host, zookeeper_port))

    jetty_home_path = __jetty_home_path(dist_directory=dist_directory, solr_version=solr_version)

    zkhost = "%s:%d" % (zookeeper_host, zookeeper_port)

    java_classpath_dirs = [
        # Solr 4
        os.path.join(solr_path, "dist", "*"),
        os.path.join(jetty_home_path, "solr-webapp", "webapp", "WEB-INF", "lib", "*"),
        os.path.join(jetty_home_path, "lib", "ext", "*"),
    ]

    args = ["java",
            "-classpath", ":".join(java_classpath_dirs),
            "-Dlog4j.configuration=file://" + os.path.abspath(log4j_properties_path),
            "org.apache.solr.cloud.ZkCLI",
            "-zkhost", zkhost] + zkcli_args

    run_command_in_foreground(args)


def update_zookeeper_solr_configuration(zookeeper_host=MC_SOLR_CLUSTER_ZOOKEEPER_HOST,
                                        zookeeper_port=MC_SOLR_CLUSTER_ZOOKEEPER_PORT,
                                        dist_directory=MC_DIST_DIR,
                                        solr_version=MC_SOLR_VERSION):
    """Update Solr's configuration on ZooKeeper."""
    if not __solr_is_installed():
        logger.info("Solr is not installed, installing...")
        __install_solr()

    if not tcp_port_is_open(hostname=zookeeper_host, port=zookeeper_port):
        raise Exception("ZooKeeper is not running at %s:%d." % (zookeeper_host, zookeeper_port))

    collections = __collections()
    logger.debug("Solr collections: %s" % collections)

    logger.info("Uploading Solr collection configurations to ZooKeeper...")
    for collection_name, collection_path in sorted(collections.items()):
        collection_conf_path = os.path.join(collection_path, "conf")

        # Copy configuration because ZooKeeper's uploader doesn't like symlinks
        logger.info("Copying collection's '%s' configuration to a temporary directory..." % collection_name)
        collection_conf_temp_dir = os.path.join(tempfile.mkdtemp(), collection_name)
        shutil.copytree(collection_conf_path, collection_conf_temp_dir)

        logger.info("Uploading collection's '%s' configuration at '%s'..." % (
            collection_name, collection_conf_temp_dir))
        __run_solr_zkcli(zkcli_args=["-cmd", "upconfig",
                                     "-confdir", collection_conf_temp_dir,
                                     "-confname", collection_name],
                         zookeeper_host=zookeeper_host,
                         zookeeper_port=zookeeper_port,
                         dist_directory=dist_directory,
                         solr_version=solr_version)

        logger.info("Linking collection's '%s' configuration..." % collection_name)
        __run_solr_zkcli(zkcli_args=["-cmd", "linkconfig",
                                     "-collection", collection_name,
                                     "-confname", collection_name],
                         zookeeper_host=zookeeper_host,
                         zookeeper_port=zookeeper_port,
                         dist_directory=dist_directory,
                         solr_version=solr_version)

    logger.info("Uploaded Solr collection configurations to ZooKeeper.")


# noinspection PyUnusedLocal
def __kill_solr_process(signum=None, frame=None):
    """Pass SIGINT/SIGTERM to child Solr when exiting."""
    global __solr_pid
    if __solr_pid is None:
        logger.warn("Solr PID is unset, probably it wasn't started.")
    else:
        gracefully_kill_child_process(child_pid=__solr_pid, sigkill_timeout=MC_SOLR_SIGKILL_TIMEOUT)
    sys.exit(signum or 0)


def __run_solr(port,
               instance_data_dir,
               hostname=fqdn(),
               jvm_heap_size=None,
               start_jar_args=None,
               jvm_opts=None,
               connect_timeout=120,
               dist_directory=MC_DIST_DIR,
               solr_version=MC_SOLR_VERSION):
    """Run Solr instance."""
    if jvm_opts is None:
        jvm_opts = MC_SOLR_STANDALONE_JVM_OPTS

    if start_jar_args is None:
        start_jar_args = []

    if not __solr_is_installed():
        logger.info("Solr is not installed, installing...")
        __install_solr()

    solr_home_dir = __solr_home_path(solr_home_dir=MC_SOLR_HOME_DIR)
    if not os.path.isdir(solr_home_dir):
        raise Exception("Solr home directory '%s' does not exist." % solr_home_dir)

    solr_path = __solr_path(dist_directory=dist_directory, solr_version=solr_version)

    if not os.path.isdir(instance_data_dir):
        logger.info("Creating data directory at %s..." % instance_data_dir)
        mkdir_p(instance_data_dir)

    logger.info("Updating collections at %s..." % instance_data_dir)
    collections = __collections(solr_home_dir=solr_home_dir)
    for collection_name, collection_path in sorted(collections.items()):
        logger.info("Updating collection '%s'..." % collection_name)

        collection_conf_src_dir = os.path.join(collection_path, "conf")
        if not os.path.isdir(collection_conf_src_dir):
            raise Exception("Configuration for collection '%s' at %s does not exist" % (
                collection_name, collection_conf_src_dir
            ))

        collection_dst_dir = os.path.join(instance_data_dir, collection_name)
        mkdir_p(collection_dst_dir)

        # Remove and copy configuration in case it has changed
        # (don't symlink because Solr 5.5+ doesn't like those)
        collection_conf_dst_dir = os.path.join(collection_dst_dir, "conf")
        if os.path.lexists(collection_conf_dst_dir):
            logger.debug("Removing old collection configuration in '%s'..." % collection_conf_dst_dir)
            if os.path.islink(collection_conf_dst_dir):
                # Might still be a link from older Solr versions
                os.unlink(collection_conf_dst_dir)
            else:
                shutil.rmtree(collection_conf_dst_dir)

        logger.info("Copying '%s' to '%s'..." % (collection_conf_src_dir, collection_conf_dst_dir))
        shutil.copytree(collection_conf_src_dir, collection_conf_dst_dir, symlinks=False)

        logger.info("Updating core.properties for collection '%s'..." % collection_name)
        core_properties_path = os.path.join(collection_dst_dir, "core.properties")
        with open(core_properties_path, 'w') as core_properties_file:
            core_properties_file.write("""
#
# This file is autogenerated. Don't bother editing it!
#

name=%(collection_name)s
instanceDir=%(instance_dir)s
""" % {
                "collection_name": collection_name,
                "instance_dir": collection_dst_dir,
            })

    logger.info("Symlinking shard configuration...")
    config_items_to_symlink = [
        "contexts",
        "etc",
        "modules",
        "resources",
        "solr.xml",
    ]
    for config_item in config_items_to_symlink:
        config_item_src_path = os.path.join(solr_home_dir, config_item)
        if not os.path.exists(config_item_src_path):
            raise Exception("Expected configuration item '%s' does not exist" % config_item_src_path)

        # Recreate symlink just in case
        config_item_dst_path = os.path.join(instance_data_dir, config_item)
        if os.path.lexists(config_item_dst_path):
            if not os.path.islink(config_item_dst_path):
                raise Exception("Configuration item '%s' exists but is not a symlink." % config_item_dst_path)
            os.unlink(config_item_dst_path)

        logger.info("Symlinking '%s' to '%s'..." % (config_item_src_path, config_item_dst_path))
        relative_symlink(config_item_src_path, config_item_dst_path)

    jetty_home_path = __jetty_home_path(dist_directory=dist_directory, solr_version=solr_version)

    logger.info("Symlinking libraries and JARs...")
    library_items_to_symlink = [
        "lib",
        "solr-webapp",
        "start.jar",
        "solr",
        "solr-webapp",
    ]
    for library_item in library_items_to_symlink:
        library_item_src_path = os.path.join(jetty_home_path, library_item)
        if not os.path.exists(library_item_src_path):
            raise Exception("Expected library item '%s' does not exist" % library_item_src_path)

        # Recreate symlink just in case
        library_item_dst_path = os.path.join(instance_data_dir, library_item)
        if os.path.lexists(library_item_dst_path):
            if not os.path.islink(library_item_dst_path):
                raise Exception("Library item '%s' exists but is not a symlink." % library_item_dst_path)
            os.unlink(library_item_dst_path)

        logger.info("Symlinking '%s' to '%s'..." % (library_item_src_path, library_item_dst_path))
        relative_symlink(library_item_src_path, library_item_dst_path)

    log4j_properties_path = os.path.join(solr_home_dir, "resources", "log4j.properties")
    if not os.path.isfile(log4j_properties_path):
        raise Exception("log4j.properties at '%s' was not found.")

    start_jar_path = os.path.join(jetty_home_path, "start.jar")
    if not os.path.isfile(start_jar_path):
        raise Exception("start.jar at '%s' was not found." % start_jar_path)

    solr_webapp_path = os.path.abspath(os.path.join(jetty_home_path, "solr-webapp"))
    if not os.path.isdir(solr_webapp_path):
        raise Exception("Solr webapp dir at '%s' was not found." % solr_webapp_path)

    if not hostname_resolves(hostname):
        raise Exception("Hostname '%s' does not resolve." % hostname)

    if tcp_port_is_open(port=port):
        raise Exception("Port %d is already open on this machine." % port)

    __raise_if_old_shards_exist()

    args = ["java"]
    logger.info("Starting Solr instance on %s, port %d..." % (hostname, port))

    if jvm_heap_size is not None:
        args += ["-Xmx%s" % jvm_heap_size]
    args += jvm_opts
    args = args + [
        "-server",
        "-Djava.util.logging.config.file=file://" + os.path.abspath(log4j_properties_path),
        "-Djetty.base=%s" % instance_data_dir,
        "-Djetty.home=%s" % instance_data_dir,
        "-Djetty.port=%d" % port,
        "-Dsolr.solr.home=%s" % instance_data_dir,
        "-Dsolr.data.dir=%s" % instance_data_dir,
        "-Dhost=%s" % hostname,
        "-Dmediacloud.luceneMatchVersion=%s" % MC_SOLR_LUCENEMATCHVERSION,

        # write heap dump to data directory on OOM errors
        "-XX:+HeapDumpOnOutOfMemoryError",
        "-XX:HeapDumpPath=%s" % instance_data_dir,

        # needed for resolving paths to JARs in solrconfig.xml
        "-Dmediacloud.solr_dist_dir=%s" % solr_path,
        "-Dmediacloud.solr_webapp_dir=%s" % solr_webapp_path,
    ]
    args = args + start_jar_args
    args = args + [
        "-jar", start_jar_path,
        "--module=http",
    ]

    logger.debug("Running command: %s" % ' '.join(args))

    process = subprocess.Popen(args)
    global __solr_pid
    __solr_pid = process.pid

    # Declare that we don't care about the exit code of the child process so
    # it doesn't become a zombie when it gets killed in signal handler
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    signal.signal(signal.SIGTERM, __kill_solr_process)  # SIGTERM is handled differently for whatever reason
    atexit.register(__kill_solr_process)

    logger.info("Solr PID: %d" % __solr_pid)

    logger.info("Solr is starting on port %d, will be available shortly..." % port)
    wait_for_tcp_port_to_open(port=port, retries=connect_timeout)

    logger.info("Solr is running on port %d!" % port)
    while True:
        time.sleep(1)


def run_solr_standalone(hostname=fqdn(),
                        port=MC_SOLR_STANDALONE_PORT,
                        base_data_dir=MC_SOLR_BASE_DATA_DIR,
                        dist_directory=MC_DIST_DIR,
                        solr_version=MC_SOLR_VERSION,
                        jvm_heap_size=MC_SOLR_STANDALONE_JVM_HEAP_SIZE):
    """Run standalone instance of Solr."""
    if not __solr_is_installed(dist_directory=dist_directory, solr_version=solr_version):
        logger.info("Solr is not installed, installing...")
        __install_solr(dist_directory=dist_directory, solr_version=solr_version)

    base_data_dir = resolve_absolute_path(name=base_data_dir, must_exist=True)
    standalone_data_dir = __standalone_data_dir(base_data_dir=base_data_dir)

    if tcp_port_is_open(port=port):
        raise Exception("Port %d is already open on this machine." % port)

    logger.info("Starting standalone Solr instance on port %d..." % port)
    __run_solr(hostname=hostname,
               port=port,
               instance_data_dir=standalone_data_dir,
               jvm_heap_size=jvm_heap_size,
               jvm_opts=MC_SOLR_STANDALONE_JVM_OPTS,
               connect_timeout=MC_SOLR_STANDALONE_CONNECT_RETRIES,
               dist_directory=dist_directory,
               solr_version=solr_version)


def run_solr_shard(shard_num,
                   shard_count,
                   hostname=fqdn(),
                   starting_port=MC_SOLR_CLUSTER_STARTING_PORT,
                   base_data_dir=MC_SOLR_BASE_DATA_DIR,
                   dist_directory=MC_DIST_DIR,
                   solr_version=MC_SOLR_VERSION,
                   zookeeper_host=MC_SOLR_CLUSTER_ZOOKEEPER_HOST,
                   zookeeper_port=MC_SOLR_CLUSTER_ZOOKEEPER_PORT,
                   jvm_heap_size=MC_SOLR_CLUSTER_JVM_HEAP_SIZE):
    """Run Solr shard, install Solr if needed; read configuration from ZooKeeper."""
    if shard_num < 1:
        raise Exception("Shard number must be 1 or greater.")
    if shard_count < 1:
        raise Exception("Shard count must be 1 or greater.")

    if not __solr_is_installed(dist_directory=dist_directory, solr_version=solr_version):
        logger.info("Solr is not installed, installing...")
        __install_solr(dist_directory=dist_directory, solr_version=solr_version)

    base_data_dir = resolve_absolute_path(name=base_data_dir, must_exist=True)

    shard_port = __shard_port(shard_num=shard_num, starting_port=starting_port)
    shard_data_dir = __shard_data_dir(shard_num=shard_num, base_data_dir=base_data_dir)

    logger.info("Waiting for ZooKeeper to start on %s:%d..." % (zookeeper_host, zookeeper_port))
    wait_for_tcp_port_to_open(hostname=zookeeper_host,
                              port=zookeeper_port,
                              retries=MC_SOLR_CLUSTER_ZOOKEEPER_CONNECT_RETRIES)
    logger.info("ZooKeeper is up!")

    logger.info("Starting Solr shard %d on port %d..." % (shard_num, shard_port))
    shard_args = [
        "-DzkHost=%s:%d" % (zookeeper_host, zookeeper_port),
        "-DnumShards=%d" % shard_count,
    ]
    __run_solr(hostname=hostname,
               port=shard_port,
               instance_data_dir=shard_data_dir,
               jvm_heap_size=jvm_heap_size,
               jvm_opts=MC_SOLR_CLUSTER_JVM_OPTS,
               start_jar_args=shard_args,
               connect_timeout=MC_SOLR_CLUSTER_CONNECT_RETRIES,
               dist_directory=dist_directory,
               solr_version=solr_version)


def reload_solr_shard(shard_num,
                      host="localhost",
                      starting_port=MC_SOLR_CLUSTER_STARTING_PORT):
    """Reload Solr shard after ZooKeeper configuration change."""
    if shard_num < 1:
        raise Exception("Shard number must be 1 or greater.")

    shard_port = __shard_port(shard_num=shard_num, starting_port=starting_port)

    if not tcp_port_is_open(hostname=host, port=shard_port):
        raise Exception("Shard %d is not running on %s:%d." % (shard_num, host, shard_port))

    logger.info("Reloading shard %d on %s:%d..." % (shard_num, host, shard_port))

    collections = __collections()
    logger.debug("Solr collections: %s" % collections)

    for collection_name, collection_path in sorted(collections.items()):
        logger.info("Reloading collection '%s' on shard %d on %s:%d..." % (
            collection_name, shard_num, host, shard_port
        ))
        url = "http://%(host)s:%(port)d/solr/admin/cores?action=RELOAD&core=%(collection_name)s" % {
            "host": host,
            "port": shard_port,
            "collection_name": collection_name,
        }
        logger.debug("Requesting URL %s..." % url)

        try:
            urllib2.urlopen(url)
        except urllib2.URLError as e:
            raise Exception("Unable to reload shard %d on %s:%d: %s" % (shard_num, host, shard_port, e.reason))

    logger.info("Reloaded shard %d on %s:%d." % (shard_num, host, shard_port))


def reload_all_solr_shards(shard_count,
                           host="localhost",
                           starting_port=MC_SOLR_CLUSTER_STARTING_PORT):
    """Reload all Solr shards after ZooKeeper configuration change."""
    if shard_count < 1:
        raise Exception("Shard count must be 1 or greater.")

    logger.info("Reloading %d shards on %s..." % (shard_count, host))
    for shard_num in range(1, shard_count + 1):
        reload_solr_shard(shard_num=shard_num, host=host, starting_port=starting_port)
    logger.info("Reloaded %d shards on %s." % (shard_count, host))


def optimize_solr_index(host="localhost",
                        port=MC_SOLR_STANDALONE_PORT,
                        collections=None):
    """Optimize collection indexes.

    In SolrCloud cluster, optimization command run on one of the shards will trigger optimization on all of them."""

    if collections is None:
        collections = __collections().keys()

    logger.debug("Solr collections to reindex: %s" % ', '.join(collections))

    if not tcp_port_is_open(hostname=host, port=port):
        raise Exception("Solr is not running on %s:%d." % (host, port))

    logger.info("Optimizing indexes on %s:%d..." % (host, port))

    for collection_name in sorted(collections):
        logger.info("Optimizing collection's '%s' index on %s:%d..." % (
            collection_name, host, port))

        url = "http://%(host)s:%(port)d/solr/%(collection_name)s/update?optimize=true" % {
            "host": host,
            "port": port,
            "collection_name": collection_name,
        }
        logger.debug("Requesting URL %s..." % url)

        try:
            urllib2.urlopen(url)
        except urllib2.URLError as e:
            raise Exception("Unable to optimize collection '%s' index on %s:%d: %s" % (
                collection_name, host, port, e.reason))

    logger.info("Optimized indexes on %s:%d." % (host, port))


def __upgrade_lucene_index(instance_data_dir,
                           dist_directory=MC_DIST_DIR,
                           solr_version=MC_SOLR_VERSION):
    """Upgrade Solr (Lucene) index using the IndexUpgrader tool in a given instance directory."""
    if not __solr_is_installed(dist_directory=dist_directory, solr_version=solr_version):
        logger.info("Solr is not installed, installing...")
        __install_solr(dist_directory=dist_directory, solr_version=solr_version)

    if not os.path.isdir(instance_data_dir):
        raise Exception("Instance data directory '%s' does not exist." % instance_data_dir)

    solr_path = __solr_path(dist_directory=dist_directory, solr_version=solr_version)

    lucene_lib_path = os.path.join(solr_path, "server", "solr-webapp", "webapp", "WEB-INF", "lib")
    if not os.path.isdir(lucene_lib_path):
        raise Exception("Lucene library directory '%s' does not exist.")

    lucene_core_jar = glob.glob(lucene_lib_path + "/lucene-core-*.jar")
    if len(lucene_core_jar) != 1:
        raise Exception("lucene-core JAR was not found in '%s'." % lucene_lib_path)
    lucene_core_jar = lucene_core_jar[0]

    lucene_backward_codecs_jar = glob.glob(lucene_lib_path + "/lucene-backward-codecs-*.jar")
    if len(lucene_backward_codecs_jar) != 1:
        raise Exception("lucene-backward-codecs JAR was not found in '%s'." % lucene_lib_path)
    lucene_backward_codecs_jar = lucene_backward_codecs_jar[0]

    collections = __collections().keys()
    for collection_name in collections:
        collection_path = os.path.join(instance_data_dir, collection_name)
        if not os.path.isdir(collection_path):
            raise Exception("Collection data directory '%s' does not exist." % collection_path)
        index_path = os.path.join(collection_path, "data", "index")
        if not os.path.isdir(index_path):
            raise Exception("Index directory '%s' does not exist." % index_path)

        logger.info("Upgrading index at path '%s'..." % index_path)
        args = [
            "java",
            "-cp", ":".join([lucene_core_jar, lucene_backward_codecs_jar]),
            "org.apache.lucene.index.IndexUpgrader",
            "-verbose",
            index_path,
        ]
        run_command_in_foreground(args)
        logger.info("Upgraded index at path '%s'." % index_path)


def upgrade_lucene_standalone_index(base_data_dir=MC_SOLR_BASE_DATA_DIR,
                                    dist_directory=MC_DIST_DIR,
                                    solr_version=MC_SOLR_VERSION):
    """Upgrade Lucene index using the IndexUpgrader tool to standalone instance."""

    base_data_dir = resolve_absolute_path(name=base_data_dir, must_exist=True)

    logger.info("Making sure standalone instance isn't running...")
    port = MC_SOLR_STANDALONE_PORT
    if tcp_port_is_open(port=port):
        raise Exception("Solr standalone instance is running on port %d." % port)
    logger.info("Made sure standalone instance isn't running.")

    logger.info("Upgrading standalone instance indexes...")
    standalone_data_dir = __standalone_data_dir(base_data_dir=base_data_dir)
    __upgrade_lucene_index(instance_data_dir=standalone_data_dir,
                           dist_directory=dist_directory,
                           solr_version=solr_version)
    logger.info("Upgraded standalone instance indexes...")


def upgrade_lucene_shards_indexes(base_data_dir=MC_SOLR_BASE_DATA_DIR,
                                  dist_directory=MC_DIST_DIR,
                                  solr_version=MC_SOLR_VERSION):
    """Upgrade Lucene indexes using the IndexUpgrader tool to all shards."""

    base_data_dir = resolve_absolute_path(name=base_data_dir, must_exist=True)

    # Try to guess shard count from how many shards are in data directory
    logger.info("Looking for shards...")
    shard_num = 0
    shard_count = 0
    while True:
        shard_num += 1
        shard_data_dir = __shard_data_dir(shard_num=shard_num, base_data_dir=base_data_dir)
        if os.path.isdir(shard_data_dir):
            shard_count += 1
        else:
            break
    if shard_count < 2:
        raise Exception("Found less than 2 shards.")
    logger.info("Found %d shards." % shard_count)

    logger.info("Making sure shards aren't running...")
    for shard_num in range(1, shard_count + 1):
        shard_port = __shard_port(shard_num=shard_num, starting_port=MC_SOLR_CLUSTER_STARTING_PORT)

        if tcp_port_is_open(port=shard_port):
            raise Exception("Solr shard %d is running on port %d." % (shard_num, shard_port))
    logger.info("Made sure shards aren't running.")

    logger.info("Upgrading shard indexes...")
    for shard_num in range(1, shard_count + 1):
        shard_data_dir = __shard_data_dir(shard_num=shard_num, base_data_dir=base_data_dir)
        __upgrade_lucene_index(instance_data_dir=shard_data_dir,
                               dist_directory=dist_directory,
                               solr_version=solr_version)
    logger.info("Upgraded shard indexes.")
