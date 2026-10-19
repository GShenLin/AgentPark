# Desktop annotation coordinate contract

## Supported source and mapping

Desktop annotations use acknowledged execution-device screenshots. Each frame ID
is bound to its execution target, physical display, image dimensions and capture
time. A call retains at most 20 entries. Clearing needs no screenshot. Drawing
prepares the native overlay automatically without screen sharing or browser pings.

Execution capture covers the full physical monitor. Encoding resizes the image
without cropping or padding. Coordinates are normalized against that complete
image: `u = image_x / image_width`, `v = image_y / image_height`.
The overlay maps them to `x = u * viewport_width`, `y = v * viewport_height`
in display-local DIP. It must not add the virtual-desktop origin or multiply by
DPI again. Electron places the window at the selected display's desktop origin.
The existing capture-to-overlay association compares physical monitor bounds.
An ellipse's x/y describe its bounding box's top-left corner, not its center.

## Renderer synchronization

The main process supplies the selected display's DIP viewport, fixes zoom to 1,
and checks content bounds after resizing the borderless overlay. The renderer
uses an explicit SVG viewBox, not the potentially stale initial 400x300 viewport.
It acknowledges only after two animation frames with matching viewport geometry;
unsynchronized geometry fails instead of reporting a displaced drawing as success.
There is no centered preview container or letterbox in this rendering path.

## Verification

- Renderer regression tests cover delayed resize, scaled normalized coordinates,
  portrait display changes and viewport mismatch rejection.
- Backend tests cover acknowledged frame geometry, retention, publish failures,
  execution-device changes and invalid image-based annotation requests.
- Frontend tests ensure voice start never captures or publishes a screen.
- A local 1920x1080 Windows/Electron draw received a successful paint acknowledgement.
  This is not pixel-level alignment verification or mixed-DPI multi-monitor hardware
  coverage; those require an additional real-device check.

These changes do not compensate for content moving after a frame was captured or
for incorrect model-selected coordinates. No deployment/restart is implied by tests.
