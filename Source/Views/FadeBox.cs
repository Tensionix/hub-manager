using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;

namespace AudionHubManager.Views;

/// <summary>
/// What does not fit fades out at its end instead of breaking off in "…" (the owner, 25.10.2026: "not ugly ellipses but
/// an ellipsis fade at the end of the block, 10-20 px"). The content is measured at its own width and drawn whole; when it
/// is wider than its place, the last <see cref="Fade"/> pixels of the place go from opaque to transparent. A content that
/// fits is drawn as it is, with no mask.
/// </summary>
public sealed class FadeBox : Decorator
{
    public double Fade { get; set; } = 16;

    double _natural, _maskedAt = -1;

    public FadeBox() => ClipToBounds = true;

    public FadeBox(Control child) : this() => Child = child;

    protected override Size MeasureOverride(Size availableSize)
    {
        if (Child is null) return default;
        Child.Measure(new Size(double.PositiveInfinity, availableSize.Height));
        _natural = Child.DesiredSize.Width;
        return new Size(Math.Min(_natural, availableSize.Width), Child.DesiredSize.Height);
    }

    protected override Size ArrangeOverride(Size finalSize)
    {
        Child?.Arrange(new Rect(0, 0, Math.Max(_natural, finalSize.Width), finalSize.Height));
        var width = _natural > finalSize.Width + 0.5 && finalSize.Width > 0 ? finalSize.Width : 0;
        if (width != _maskedAt)
        {
            _maskedAt = width;
            OpacityMask = width <= 0 ? null : new LinearGradientBrush
            {
                StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
                EndPoint = new RelativePoint(1, 0, RelativeUnit.Relative),
                GradientStops = { new GradientStop(Colors.Black, Math.Max(0, 1 - Fade / width)), new GradientStop(Colors.Transparent, 1) },
            };
        }
        return finalSize;
    }
}
