import { useState } from 'react'
import { useI18n } from './i18n'

export default function Settings() {
  const { t, locale, setLocale, settings, updateSettings, resetSettings } = useI18n()
  const [notice, setNotice] = useState('')
  const change = (patch: Parameters<typeof updateSettings>[0]) => { updateSettings(patch); setNotice(t('settingsSaved')); window.setTimeout(() => setNotice(''), 2200) }
  const reset = () => { resetSettings(); setNotice(t('settingsReset')); window.setTimeout(() => setNotice(''), 2200) }
  return <section className="settings-page">
    <div className="page-intro"><div><p className="eyebrow">{t('settingsTitle').toUpperCase()}</p><h2>{t('settingsTitle')}</h2><p>{t('settingsDescription')}</p></div>{notice && <div className="settings-notice">{notice}</div>}</div>
    <div className="settings-grid">
      <div className="content-card settings-card"><div className="settings-card-header"><div><p className="eyebrow">{t('generalSettings').toUpperCase()}</p><h3>{t('generalSettings')}</h3></div></div>
        <div className="settings-list">
          <label className="setting-row"><span><strong>{t('language')}</strong><small>{t('languageDescription')}</small></span><select value={locale} onChange={event => setLocale(event.target.value as 'ru' | 'en' | 'kk')}><option value="ru">{t('languageRussian')}</option><option value="en">{t('languageEnglish')}</option><option value="kk">{t('languageKazakh')}</option></select></label>
          <label className="setting-row"><span><strong>{t('dateFormat')}</strong><small>{t('dateFormatDescription')}</small></span><select value={settings.dateFormat} onChange={event => change({ dateFormat: event.target.value as 'locale' | 'iso' })}><option value="locale">{t('localDate')}</option><option value="iso">{t('isoDate')}</option></select></label>
          <label className="setting-row"><span><strong>{t('numberFormat')}</strong><small>{t('numberFormatDescription')}</small></span><select value={settings.numberFormat} onChange={event => change({ numberFormat: event.target.value as 'locale' | 'plain' })}><option value="locale">{t('localeNumbers')}</option><option value="plain">{t('plainNumbers')}</option></select></label>
          <label className="setting-row setting-switch"><span><strong>{t('compactMode')}</strong><small>{t('compactModeDescription')}</small></span><input type="checkbox" checked={settings.compactMode} onChange={event => change({ compactMode: event.target.checked })} /></label>
          <label className="setting-row setting-switch"><span><strong>{t('autoOpenDraft')}</strong><small>{t('autoOpenDraftDescription')}</small></span><input type="checkbox" checked={settings.autoOpenDraft} onChange={event => change({ autoOpenDraft: event.target.checked })} /></label>
        </div>
        <div className="settings-footer"><button className="button subtle" onClick={reset}>{t('resetSettings')}</button></div>
      </div>
    </div>
  </section>
}
