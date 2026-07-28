/**
 * BaseIcon — CrewFit "Base" tab icon (Aviation + Crew + Community).
 *
 * Line-based crew silhouettes flanked by minimalist aircraft-wing arcs.
 * Kept in the same stroke weight / matte tone as the other tab icons in
 * <PremiumTabBar>. Two versions: outline (inactive) + filled (active).
 */
import React from "react";
import Svg, { Path, Circle } from "react-native-svg";

export function BaseIcon({
  size = 24,
  color = "#8a8a8a",
  filled = false,
}: {
  size?: number;
  color?: string;
  filled?: boolean;
}) {
  const stroke = color;
  const fill = filled ? color : "none";
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {/* Left wing */}
      <Path
        d="M1.5 12.5 C 3.5 11.8, 5 11.6, 6.3 12"
        stroke={stroke}
        strokeWidth={1.6}
        strokeLinecap="round"
        fill="none"
      />
      {/* Right wing */}
      <Path
        d="M22.5 12.5 C 20.5 11.8, 19 11.6, 17.7 12"
        stroke={stroke}
        strokeWidth={1.6}
        strokeLinecap="round"
        fill="none"
      />
      {/* Central subtle upward-swept wingtip line (aviation nod) */}
      <Path
        d="M8 6.5 L 12 4 L 16 6.5"
        stroke={stroke}
        strokeWidth={1.4}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      {/* Left crew silhouette — head */}
      <Circle cx={8.5} cy={11} r={2.1} stroke={stroke} strokeWidth={1.5} fill={fill} />
      {/* Right crew silhouette — head */}
      <Circle cx={15.5} cy={11} r={2.1} stroke={stroke} strokeWidth={1.5} fill={fill} />
      {/* Left shoulders/torso */}
      <Path
        d="M5.5 19.5 C 5.5 16.8, 7 15.5, 8.5 15.5 C 10 15.5, 11.5 16.8, 11.5 19.5"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        fill={fill}
      />
      {/* Right shoulders/torso */}
      <Path
        d="M12.5 19.5 C 12.5 16.8, 14 15.5, 15.5 15.5 C 17 15.5, 18.5 16.8, 18.5 19.5"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        fill={fill}
      />
    </Svg>
  );
}

export default BaseIcon;
