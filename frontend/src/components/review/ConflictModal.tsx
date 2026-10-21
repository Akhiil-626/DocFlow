import React, { useState } from 'react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { AlertTriangle, Eye, EyeOff, RotateCcw } from 'lucide-react';

interface ConflictModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirmReload: () => void;
  unsavedEditsSummary?: Record<string, string>;
}

export const ConflictModal: React.FC<ConflictModalProps> = ({
  isOpen,
  onClose,
  onConfirmReload,
  unsavedEditsSummary = {},
}) => {
  const [showEdits, setShowEdits] = useState(false);

  const editEntries = Object.entries(unsavedEditsSummary);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Conflict: Document Modified"
      maxWidth="md"
      footer={
        <div className="flex items-center justify-between w-full">
          <Button variant="secondary" onClick={onClose} data-testid="keep-my-edits-btn">
            Keep My Edits
          </Button>
          <Button
            variant="danger"
            onClick={onConfirmReload}
            className="gap-1.5"
            data-testid="discard-and-reload-btn"
          >
            <RotateCcw className="w-4 h-4" />
            <span>Discard Edits & Reload Latest</span>
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="flex items-start gap-3 p-3 bg-amber-50 border border-amber-200 rounded-xl text-amber-900 text-sm">
          <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="font-semibold text-amber-950">
              This invoice was changed by someone else
            </h4>
            <p className="text-xs text-amber-800">
              Another reviewer has already saved modifications or changed this invoice&apos;s
              extraction version. To avoid overwriting their work, your changes have not been saved.
            </p>
          </div>
        </div>

        {editEntries.length > 0 && (
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setShowEdits(!showEdits)}
              className="text-xs text-sky-600 hover:text-sky-800 font-medium inline-flex items-center gap-1"
            >
              {showEdits ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              <span>{showEdits ? 'Hide my unsaved edits' : 'View my unsaved edits'}</span>
            </button>

            {showEdits && (
              <div
                className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs space-y-1 font-mono max-h-48 overflow-y-auto"
                data-testid="unsaved-edits-diff"
              >
                <p className="font-sans font-semibold text-[11px] text-gray-500 uppercase mb-1">
                  Your Pending Changes:
                </p>
                {editEntries.map(([field, val]) => (
                  <div key={field} className="flex items-center justify-between">
                    <span className="font-semibold text-gray-700">{field}:</span>
                    <span className="text-sky-700 bg-sky-50 px-1.5 py-0.5 rounded">{val}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <p className="text-xs text-gray-500">
          Click <strong>Keep My Edits</strong> to inspect your work or copy your inputs.
          Click <strong>Discard Edits &amp; Reload Latest</strong> to load the newest version from the server.
        </p>
      </div>
    </Modal>
  );
};
