# Copyright (C) 2015 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import fixtures

from nodepool import builder, exceptions, fakeprovider, tests
from nodepool import zk


class TestNodepoolBuilderDibImage(tests.BaseTestCase):
    def test_from_path(self):
        image = builder.DibImageFile.from_path(
            '/foo/bar/myid1234.qcow2')
        self.assertEqual(image.image_id, 'myid1234')
        self.assertEqual(image.extension, 'qcow2')

    def test_from_image_id(self):
        tempdir = fixtures.TempDir()
        self.useFixture(tempdir)
        image_path = os.path.join(tempdir.path, 'myid1234.qcow2')
        open(image_path, 'w')

        images = builder.DibImageFile.from_image_id(tempdir.path, 'myid1234')
        self.assertEqual(len(images), 1)

        image = images[0]
        self.assertEqual(image.image_id, 'myid1234')
        self.assertEqual(image.extension, 'qcow2')

    def test_from_id_multiple(self):
        tempdir = fixtures.TempDir()
        self.useFixture(tempdir)
        image_path_1 = os.path.join(tempdir.path, 'myid1234.qcow2')
        image_path_2 = os.path.join(tempdir.path, 'myid1234.raw')
        open(image_path_1, 'w')
        open(image_path_2, 'w')

        images = builder.DibImageFile.from_image_id(tempdir.path, 'myid1234')
        images = sorted(images, key=lambda x: x.extension)
        self.assertEqual(len(images), 2)

        self.assertEqual(images[0].extension, 'qcow2')
        self.assertEqual(images[1].extension, 'raw')

    def test_from_images_dir(self):
        tempdir = fixtures.TempDir()
        self.useFixture(tempdir)
        image_path_1 = os.path.join(tempdir.path, 'myid1234.qcow2')
        image_path_2 = os.path.join(tempdir.path, 'myid1234.raw')
        open(image_path_1, 'w')
        open(image_path_2, 'w')

        images = builder.DibImageFile.from_images_dir(tempdir.path)
        images = sorted(images, key=lambda x: x.extension)
        self.assertEqual(len(images), 2)

        self.assertEqual(images[0].image_id, 'myid1234')
        self.assertEqual(images[0].extension, 'qcow2')
        self.assertEqual(images[1].image_id, 'myid1234')
        self.assertEqual(images[1].extension, 'raw')

    def test_to_path(self):
        image = builder.DibImageFile('myid1234', 'qcow2')
        self.assertEqual(image.to_path('/imagedir'),
                         '/imagedir/myid1234.qcow2')
        self.assertEqual(image.to_path('/imagedir/'),
                         '/imagedir/myid1234.qcow2')
        self.assertEqual(image.to_path('/imagedir/', False),
                         '/imagedir/myid1234')

        image = builder.DibImageFile('myid1234')
        self.assertRaises(exceptions.BuilderError, image.to_path, '/imagedir/')

class TestNodePoolBuilder(tests.DBTestCase):
    def test_start_stop(self):
        config = self.setup_config('node.yaml')
        nb = builder.NodePoolBuilder(config)
        nb.cleanup_interval = .5
        nb.build_interval = .1
        nb.upload_interval = .1
        nb.start()
        nb.stop()

    def test_image_upload_fail(self):
        """Test that image upload fails are handled properly."""

        # Now swap out the upload fake so that the next uploads fail
        fake_client = fakeprovider.FakeUploadFailCloud(times_to_fail=1)

        def get_fake_client(*args, **kwargs):
            return fake_client

        self.useFixture(fixtures.MonkeyPatch(
            'nodepool.provider_manager.FakeProviderManager._getClient',
            get_fake_client))
        self.useFixture(fixtures.MonkeyPatch(
            'nodepool.nodepool._get_one_cloud',
            fakeprovider.fake_get_one_cloud))

        configfile = self.setup_config('node.yaml')
        pool = self.useNodepool(configfile, watermark_sleep=1)
        self._useBuilder(configfile)
        pool.start()
        self.waitForImage('fake-provider', 'fake-image')
        self.waitForNodes(pool)

        newest_builds = self.zk.getMostRecentBuilds(1, 'fake-image',
                                                    state=zk.READY)
        self.assertEqual(1, len(newest_builds))

        uploads = self.zk.getUploads('fake-image', newest_builds[0].id,
                                     'fake-provider', states=[zk.FAILED])
        self.assertEqual(1, len(uploads))

    def test_provider_addition(self):
        configfile = self.setup_config('node.yaml')
        self._useBuilder(configfile)
        self.waitForImage('fake-provider', 'fake-image')
        self.replace_config(configfile, 'node_two_provider.yaml')
        self.waitForImage('fake-provider2', 'fake-image')

    def test_provider_removal(self):
        configfile = self.setup_config('node_two_provider.yaml')
        self._useBuilder(configfile)
        self.waitForImage('fake-provider', 'fake-image')
        self.waitForImage('fake-provider2', 'fake-image')
        image = self.zk.getMostRecentImageUpload('fake-provider', 'fake-image')
        self.replace_config(configfile, 'node_two_provider_remove.yaml')
        self.waitForImageDeletion('fake-provider2', 'fake-image')
        image2 = self.zk.getMostRecentImageUpload('fake-provider', 'fake-image')
        self.assertEqual(image, image2)

    def test_image_addition(self):
        configfile = self.setup_config('node.yaml')
        self._useBuilder(configfile)
        self.waitForImage('fake-provider', 'fake-image')
        self.replace_config(configfile, 'node_two_image.yaml')
        self.waitForImage('fake-provider', 'fake-image2')

    def test_image_removal(self):
        configfile = self.setup_config('node_two_image.yaml')
        self._useBuilder(configfile)
        self.waitForImage('fake-provider', 'fake-image')
        self.waitForImage('fake-provider', 'fake-image2')
        self.replace_config(configfile, 'node_two_image_remove.yaml')
        self.waitForImageDeletion('fake-provider', 'fake-image2')
        self.waitForBuildDeletion('fake-image2', '0000000001')

    def test_image_rebuild_age(self):
        self._test_image_rebuild_age()

    def _test_image_rebuild_age(self, expire=86400):
        configfile = self.setup_config('node.yaml')
        self._useBuilder(configfile)
        build = self.waitForBuild('fake-image', '0000000001')
        image = self.waitForImage('fake-provider', 'fake-image')
        # Expire rebuild-age (default: 1day) to force a new build.
        build.state_time -= expire
        with self.zk.imageBuildLock('fake-image', blocking=True, timeout=1):
            self.zk.storeBuild('fake-image', build, '0000000001')
        self.waitForBuild('fake-image', '0000000002')
        self.waitForImage('fake-provider', 'fake-image', [image])
        builds = self.zk.getBuilds('fake-image', zk.READY)
        self.assertEqual(len(builds), 2)
        return (build, image)

    def test_image_rotation(self):
        # Expire rebuild-age (2days), to avoid problems when expiring 2 images.
        self._test_image_rebuild_age(expire=172800)
        build = self.waitForBuild('fake-image', '0000000002')
        # Expire rebuild-age (default: 1day) to force a new build.
        build.state_time -= 86400
        with self.zk.imageBuildLock('fake-image', blocking=True, timeout=1):
            self.zk.storeBuild('fake-image', build, '0000000002')
        self.waitForBuildDeletion('fake-image', '0000000001')
        self.waitForBuild('fake-image', '0000000003')
        builds = self.zk.getBuilds('fake-image', zk.READY)
        self.assertEqual(len(builds), 2)

    def test_image_rotation_invalid_external_name(self):
        # NOTE(pabelanger): We are forcing fake-image to leak in fake-provider.
        # We do this to test our CleanupWorker will properly delete diskimage
        # builds from the HDD. For this test, we don't care about the leaked
        # image.
        #
        # Ensure we have a total of 3 diskimages on disk, so we can confirm
        # nodepool-builder will properly purge the 1 diskimage build leaving a
        # total of 2 diskimages on disk at all times.

        # Expire rebuild-age (2days), to avoid problems when expiring 2 images.
        build001, image001 = self._test_image_rebuild_age(expire=172800)
        build002 = self.waitForBuild('fake-image', '0000000002')

        # Make sure 2rd diskimage build was uploaded.
        image002 = self.waitForImage('fake-provider', 'fake-image', [image001])
        self.assertEqual(image002.build_id, '0000000002')

        # Delete external name / id so we can test exception handlers.
        upload = self.zk.getUploads(
            'fake-image', '0000000001', 'fake-provider', zk.READY)[0]
        upload.external_name = None
        upload.external_id = None
        with self.zk.imageUploadLock(upload.image_name, upload.build_id,
                                     upload.provider_name, blocking=True,
                                     timeout=1):
            self.zk.storeImageUpload(upload.image_name, upload.build_id,
                                     upload.provider_name, upload, upload.id)

        # Expire rebuild-age (default: 1day) to force a new build.
        build002.state_time -= 86400
        with self.zk.imageBuildLock('fake-image', blocking=True, timeout=1):
            self.zk.storeBuild('fake-image', build002, '0000000002')
        self.waitForBuildDeletion('fake-image', '0000000001')

        # Make sure fake-image for fake-provider is removed from zookeeper.
        upload = self.zk.getUploads(
            'fake-image', '0000000001', 'fake-provider')
        self.assertEqual(len(upload), 0)
        self.waitForBuild('fake-image', '0000000003')

        # Ensure we only have 2 builds on disk.
        builds = self.zk.getBuilds('fake-image', zk.READY)
        self.assertEqual(len(builds), 2)

        # Make sure 3rd diskimage build was uploaded.
        image003 = self.waitForImage(
            'fake-provider', 'fake-image', [image001, image002])
        self.assertEqual(image003.build_id, '0000000003')

    def test_cleanup_hard_upload_fails(self):
        configfile = self.setup_config('node.yaml')
        self._useBuilder(configfile)
        self.waitForImage('fake-provider', 'fake-image')

        upload = self.zk.getUploads('fake-image', '0000000001',
                                    'fake-provider', zk.READY)[0]

        # Store a new ZK node as UPLOADING to represent a hard fail
        upload.state = zk.UPLOADING

        with self.zk.imageUploadLock(upload.image_name, upload.build_id,
                                     upload.provider_name, blocking=True,
                                     timeout=1):
            upnum = self.zk.storeImageUpload(upload.image_name,
                                             upload.build_id,
                                             upload.provider_name,
                                             upload)

        # Now it should disappear from the current build set of uploads
        self.waitForUploadRecordDeletion(upload.provider_name,
                                         upload.image_name,
                                         upload.build_id,
                                         upnum)

    def test_cleanup_failed_image_build(self):
        configfile = self.setup_config('node_diskimage_fail.yaml')
        self._useBuilder(configfile)
        # NOTE(pabelanger): We are racing here, but don't really care. We just
        # need our first image build to fail.
        self.replace_config(configfile, 'node.yaml')
        self.waitForImage('fake-provider', 'fake-image')
        # Make sure our cleanup worker properly removes the first build.
        self.waitForBuildDeletion('fake-image', '0000000001')

    def test_diskimage_build_only(self):
        configfile = self.setup_config('node_diskimage_only.yaml')
        self._useBuilder(configfile)
        self.waitForBuild('fake-image', '0000000001')
