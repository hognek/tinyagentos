### Fixed
- Image Viewer and Media Player now display the basename of a routed file URL in their title bar: the final URL segment is decoded before the directory path is stripped, so a nested route like `nested/photo.png` no longer leaks into the displayed file name.
