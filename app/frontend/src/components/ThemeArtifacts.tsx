import type { UiThemeId } from "../themes";

function EditorialArtifacts() {
  return (
    <div className="editorialArtifacts" aria-hidden="true">
      <span className="artSlice artSliceOne" />
      <span className="artSlice artSliceTwo" />
      <span className="artSlice artSliceThree" />
      <span className="artFrame artFrameOne" />
      <span className="artFrame artFrameTwo" />
      <span className="artType artTypeOne">A</span>
      <span className="artType artTypeTwo">03</span>
      <span className="artRule artRuleOne" />
      <span className="artRule artRuleTwo" />
    </div>
  );
}

function KleeThemeArtifacts() {
  return (
    <div className="kleeAdventureArtifacts" aria-hidden="true">
      <span className="kleeHeroSticker">
        <span className="kleeHeroGlow" />
      </span>
      <span className="kleeSticker kleeStickerBomb" />
      <span className="kleeSticker kleeStickerSpark" />
      <span className="kleeSticker kleeStickerDodoco" />
      <span className="kleeSticker kleeStickerClover" />
      <span className="kleeSticker kleeStickerVision" />
      <span className="kleeRibbon kleeRibbonTop" />
      <span className="kleeRibbon kleeRibbonBottom" />
      <span className="kleeSparkTrail kleeSparkTrailOne" />
      <span className="kleeSparkTrail kleeSparkTrailTwo" />
    </div>
  );
}

export function ThemeArtifacts({ theme }: { theme: UiThemeId }) {
  return theme === "klee_bomb" ? <KleeThemeArtifacts /> : <EditorialArtifacts />;
}
